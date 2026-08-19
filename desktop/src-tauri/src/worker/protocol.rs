use std::collections::BTreeMap;
use std::fmt;
use std::io::{BufRead, Write};

use serde::de::{self, DeserializeOwned, MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::{Map, Number, Value};
use uuid::Uuid;
use zeroize::Zeroizing;

use crate::{AppError, AppResult};

pub const PROTOCOL_VERSION: &str = "1.0.0";
pub const PAYLOAD_SCHEMA_VERSION: &str = "1.0.0";
pub const MAX_FRAME_BYTES: usize = 4 * 1024 * 1024;
pub const HANDSHAKE_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(5);

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct WorkerHello {
    pub message_type: String,
    pub protocol_version: String,
    pub worker_version: String,
    pub target: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct WorkerEnvelope<T> {
    pub protocol_version: String,
    pub request_id: Uuid,
    pub message_type: String,
    pub payload: T,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ShutdownPayload {
    pub schema_version: String,
    pub reason: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ShutdownAck {
    pub schema_version: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ResearchPreviewResult {
    pub schema_version: String,
    pub normalized_intent: Value,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ResearchProgress {
    pub schema_version: String,
    pub job_id: Uuid,
    pub percent: i64,
    pub phase: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ProviderOutcome {
    pub provider_run_id: Uuid,
    pub planned_call_id: Uuid,
    pub provider: String,
    pub outcome: String,
    pub configured_model: Option<String>,
    pub resolved_model: Option<String>,
    pub provider_request_id: Option<String>,
    pub requests: Option<i64>,
    pub input_tokens: Option<i64>,
    pub cached_input_tokens: Option<i64>,
    pub output_tokens: Option<i64>,
    pub reasoning_tokens: Option<i64>,
    pub tool_invocations: Option<i64>,
    pub repair_used: Option<bool>,
    pub tool_usage: Vec<String>,
    pub provider_native_ticks: Option<String>,
    pub output_sha256: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ResearchResultPayload {
    pub schema_version: String,
    pub job_id: Uuid,
    pub result: Value,
    pub evidence_sources: Vec<Value>,
    pub evidence_claims: Vec<Value>,
    pub provider_outcomes: Vec<ProviderOutcome>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ResearchTerminalDetail {
    pub schema_version: String,
    pub job_id: Uuid,
    pub message: String,
    #[serde(default)]
    pub provider_outcomes: Vec<ProviderOutcome>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct CancelAck {
    pub schema_version: String,
    pub job_id: Uuid,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ProviderPreflightResult {
    pub schema_version: String,
    pub provider: String,
    pub available: bool,
    pub resolved_model: Option<String>,
    pub retention_mode: String,
    pub data_use_mode: String,
    pub no_storage_mode: String,
    pub privacy_mode: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ProviderPreflightError {
    pub schema_version: String,
    pub provider: String,
    pub message: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, Eq, PartialEq)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ProviderStarted {
    pub schema_version: String,
    pub job_id: Uuid,
    pub provider_run_id: Uuid,
    pub planned_call_id: Uuid,
}

#[derive(Debug, Clone)]
pub enum WorkerMessage {
    ResearchPreviewResult(ResearchPreviewResult),
    ResearchProgress(ResearchProgress),
    ResearchResult(ResearchResultPayload),
    ResearchRefusal(ResearchTerminalDetail),
    ResearchIncomplete(ResearchTerminalDetail),
    ResearchCancelled(ResearchTerminalDetail),
    ResearchError(ResearchTerminalDetail),
    ResearchCancelAck(CancelAck),
    ProviderPreflightResult(ProviderPreflightResult),
    ProviderPreflightError(ProviderPreflightError),
    ProviderStarted(ProviderStarted),
    ShutdownAck(ShutdownAck),
}

impl WorkerMessage {
    pub fn is_terminal_for_active_request(&self) -> bool {
        !matches!(self, Self::ResearchProgress(_) | Self::ResearchCancelAck(_) | Self::ProviderStarted(_))
    }
}

pub fn decode_worker_message(value: Value) -> AppResult<(Uuid, WorkerMessage)> {
    let envelope: WorkerEnvelope<Value> = serde_json::from_value(value)
        .map_err(|_| AppError::Worker("worker response violates its envelope schema".to_owned()))?;
    if envelope.protocol_version != PROTOCOL_VERSION {
        return Err(AppError::Worker("worker response protocol version mismatch".to_owned()));
    }
    let message = match envelope.message_type.as_str() {
        "research.preview.result" => WorkerMessage::ResearchPreviewResult(decode_payload(envelope.payload)?),
        "research.progress" => WorkerMessage::ResearchProgress(decode_payload(envelope.payload)?),
        "research.result" => WorkerMessage::ResearchResult(decode_payload(envelope.payload)?),
        "research.refusal" => WorkerMessage::ResearchRefusal(decode_payload(envelope.payload)?),
        "research.incomplete" => WorkerMessage::ResearchIncomplete(decode_payload(envelope.payload)?),
        "research.cancelled" => WorkerMessage::ResearchCancelled(decode_payload(envelope.payload)?),
        "research.error" => WorkerMessage::ResearchError(decode_payload(envelope.payload)?),
        "research.cancel.ack" => WorkerMessage::ResearchCancelAck(decode_payload(envelope.payload)?),
        "provider.preflight.result" => WorkerMessage::ProviderPreflightResult(decode_payload(envelope.payload)?),
        "provider.preflight.error" => WorkerMessage::ProviderPreflightError(decode_payload(envelope.payload)?),
        "provider.started" => WorkerMessage::ProviderStarted(decode_payload(envelope.payload)?),
        "shutdown.ack" => WorkerMessage::ShutdownAck(decode_payload(envelope.payload)?),
        _ => return Err(AppError::Worker("worker emitted an unknown message type".to_owned())),
    };
    validate_payload_version(&message)?;
    Ok((envelope.request_id, message))
}

fn decode_payload<T: DeserializeOwned>(value: Value) -> AppResult<T> {
    serde_json::from_value(value)
        .map_err(|_| AppError::Worker("worker response payload violates its strict schema".to_owned()))
}

fn validate_payload_version(message: &WorkerMessage) -> AppResult<()> {
    let version = match message {
        WorkerMessage::ResearchPreviewResult(value) => &value.schema_version,
        WorkerMessage::ResearchProgress(value) => &value.schema_version,
        WorkerMessage::ResearchResult(value) => &value.schema_version,
        WorkerMessage::ResearchRefusal(value)
        | WorkerMessage::ResearchIncomplete(value)
        | WorkerMessage::ResearchCancelled(value)
        | WorkerMessage::ResearchError(value) => &value.schema_version,
        WorkerMessage::ResearchCancelAck(value) => &value.schema_version,
        WorkerMessage::ProviderPreflightResult(value) => &value.schema_version,
        WorkerMessage::ProviderPreflightError(value) => &value.schema_version,
        WorkerMessage::ProviderStarted(value) => &value.schema_version,
        WorkerMessage::ShutdownAck(value) => &value.schema_version,
    };
    if version != PAYLOAD_SCHEMA_VERSION {
        return Err(AppError::Worker("worker payload schema version mismatch".to_owned()));
    }
    Ok(())
}

pub fn read_frame<R: BufRead, T: DeserializeOwned>(reader: &mut R) -> AppResult<T> {
    let frame = read_frame_bytes(reader)?;
    let value = parse_strict_json_bytes(&frame)?;
    serde_json::from_value(value)
        .map_err(|_| AppError::Worker("worker protocol frame is malformed or violates its schema".to_owned()))
}

fn read_frame_bytes<R: BufRead>(reader: &mut R) -> AppResult<Vec<u8>> {
    let mut frame = Vec::new();
    loop {
        let available = reader.fill_buf()?;
        if available.is_empty() {
            return Err(AppError::Worker(if frame.is_empty() {
                "worker stdout reached unexpected EOF".to_owned()
            } else {
                "worker stdout ended with a truncated frame".to_owned()
            }));
        }
        let newline = available.iter().position(|byte| *byte == b'\n');
        let take = newline.map_or(available.len(), |position| position + 1);
        if frame.len().saturating_add(take) > MAX_FRAME_BYTES + 1 {
            return Err(AppError::Worker("worker protocol frame exceeded 4 MiB".to_owned()));
        }
        frame.extend_from_slice(&available[..take]);
        reader.consume(take);
        if newline.is_some() { break; }
    }
    if frame.last() != Some(&b'\n') || frame.get(frame.len().saturating_sub(2)) == Some(&b'\r') {
        return Err(AppError::Worker("worker protocol requires LF-terminated UTF-8 JSON".to_owned()));
    }
    frame.pop();
    if frame.is_empty() || frame.len() > MAX_FRAME_BYTES {
        return Err(AppError::Worker("worker protocol frame is empty or oversized".to_owned()));
    }
    if std::str::from_utf8(&frame).is_err() {
        return Err(AppError::Worker("worker protocol frame is not UTF-8".to_owned()));
    }
    Ok(frame)
}

pub(crate) fn parse_strict_json_bytes(frame: &[u8]) -> AppResult<Value> {
    let mut deserializer = serde_json::Deserializer::from_slice(frame);
    let value = StrictJsonValue::deserialize(&mut deserializer)
        .map_err(|_| AppError::Worker("worker protocol JSON is invalid or contains duplicate keys".to_owned()))?;
    deserializer.end()
        .map_err(|_| AppError::Worker("worker protocol JSON contains trailing data".to_owned()))?;
    Ok(value.0)
}

struct StrictJsonValue(Value);

impl<'de> Deserialize<'de> for StrictJsonValue {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserializer.deserialize_any(StrictValueVisitor)
    }
}

struct StrictValueVisitor;

impl<'de> Visitor<'de> for StrictValueVisitor {
    type Value = StrictJsonValue;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("strict JSON without duplicate object keys")
    }

    fn visit_bool<E: de::Error>(self, value: bool) -> Result<Self::Value, E> { Ok(StrictJsonValue(Value::Bool(value))) }
    fn visit_i64<E: de::Error>(self, value: i64) -> Result<Self::Value, E> { Ok(StrictJsonValue(Value::Number(value.into()))) }
    fn visit_u64<E: de::Error>(self, value: u64) -> Result<Self::Value, E> { Ok(StrictJsonValue(Value::Number(value.into()))) }
    fn visit_f64<E: de::Error>(self, value: f64) -> Result<Self::Value, E> {
        Number::from_f64(value).map(|number| StrictJsonValue(Value::Number(number)))
            .ok_or_else(|| E::custom("non-finite JSON number"))
    }
    fn visit_str<E: de::Error>(self, value: &str) -> Result<Self::Value, E> { Ok(StrictJsonValue(Value::String(value.to_owned()))) }
    fn visit_string<E: de::Error>(self, value: String) -> Result<Self::Value, E> { Ok(StrictJsonValue(Value::String(value))) }
    fn visit_none<E: de::Error>(self) -> Result<Self::Value, E> { Ok(StrictJsonValue(Value::Null)) }
    fn visit_unit<E: de::Error>(self) -> Result<Self::Value, E> { Ok(StrictJsonValue(Value::Null)) }

    fn visit_seq<A: SeqAccess<'de>>(self, mut sequence: A) -> Result<Self::Value, A::Error> {
        let mut values = Vec::new();
        while let Some(value) = sequence.next_element::<StrictJsonValue>()? { values.push(value.0); }
        Ok(StrictJsonValue(Value::Array(values)))
    }

    fn visit_map<A: MapAccess<'de>>(self, mut object: A) -> Result<Self::Value, A::Error> {
        let mut values = BTreeMap::<String, Value>::new();
        while let Some(key) = object.next_key::<String>()? {
            if values.contains_key(&key) { return Err(de::Error::custom("duplicate object key")); }
            let value = object.next_value::<StrictJsonValue>()?;
            values.insert(key, value.0);
        }
        Ok(StrictJsonValue(Value::Object(values.into_iter().collect::<Map<_, _>>())))
    }
}

pub fn write_frame<W: Write, T: Serialize>(writer: &mut W, value: &T) -> AppResult<()> {
    let frame = Zeroizing::new(serde_json::to_vec(value)?);
    if frame.is_empty() || frame.len() > MAX_FRAME_BYTES || frame.contains(&b'\n') {
        return Err(AppError::Worker("outbound worker frame is empty or oversized".to_owned()));
    }
    writer.write_all(&frame)?;
    writer.write_all(b"\n")?;
    writer.flush()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[derive(Debug, Deserialize, Eq, PartialEq)]
    #[serde(deny_unknown_fields)]
    struct Example { value: u32 }

    #[test]
    fn accepts_one_strict_lf_json_object() {
        let mut input = Cursor::new(b"{\"value\":7}\n");
        assert_eq!(read_frame::<_, Example>(&mut input).unwrap(), Example { value: 7 });
    }

    #[test]
    fn rejects_malformed_truncated_unknown_duplicate_nested_and_oversized_frames() {
        assert!(read_frame::<_, Example>(&mut Cursor::new(b"{}".as_slice())).is_err());
        assert!(read_frame::<_, Example>(&mut Cursor::new(b"{\"value\":7,\"extra\":1}\n".as_slice())).is_err());
        assert!(read_frame::<_, Value>(&mut Cursor::new(b"{\"outer\":{\"x\":1,\"x\":2}}\n".as_slice())).is_err());
        assert!(read_frame::<_, Value>(&mut Cursor::new(b"{\"x\":NaN}\n".as_slice())).is_err());
        assert!(read_frame::<_, Example>(&mut Cursor::new(vec![b'x'; MAX_FRAME_BYTES + 2])).is_err());
        assert!(read_frame::<_, Example>(&mut Cursor::new(b"{\"value\":7}\r\n".as_slice())).is_err());
    }

    #[test]
    fn writer_is_lf_terminated_and_round_trips() {
        let envelope = WorkerEnvelope {
            protocol_version: PROTOCOL_VERSION.into(),
            request_id: Uuid::new_v4(),
            message_type: "test".into(),
            payload: serde_json::json!({"bounded": true}),
        };
        let mut output = Vec::new();
        write_frame(&mut output, &envelope).unwrap();
        assert_eq!(output.last(), Some(&b'\n'));
    }

    #[test]
    fn unknown_worker_message_type_fails_closed() {
        let value = serde_json::json!({
            "protocolVersion": PROTOCOL_VERSION,
            "requestId": Uuid::new_v4(),
            "messageType": "research.surprise",
            "payload": {"schemaVersion": PAYLOAD_SCHEMA_VERSION}
        });
        assert!(decode_worker_message(value).is_err());
    }
}
