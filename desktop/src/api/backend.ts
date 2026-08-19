import { invoke } from "@tauri-apps/api/core";

import type {
  CostPreview,
  CredentialProvider,
  CredentialStatusView,
  DiagnosticsView,
  ResearchIntentInput,
  ResearchRunView,
} from "../domain/contracts";

const MAX_PROMPT_CHARACTERS = 4_000;
const MAX_SECRET_BYTES = 2_560;

export interface BackendApi {
  getDiagnostics(): Promise<DiagnosticsView>;
  setProjectBudget(hardBudgetMicroUsd: number): Promise<void>;
  previewResearch(intent: ResearchIntentInput): Promise<CostPreview>;
  startResearch(intent: ResearchIntentInput, consentToken: string): Promise<ResearchRunView>;
  getResearchRun(jobId: string): Promise<ResearchRunView>;
  cancelResearch(jobId: string): Promise<ResearchRunView>;
  openEvidenceLink(linkHandle: string): Promise<void>;
  getCredentialStatus(provider: CredentialProvider): Promise<CredentialStatusView>;
  storeCredential(provider: CredentialProvider, secret: string): Promise<CredentialStatusView>;
  validateCredential(provider: CredentialProvider): Promise<CredentialStatusView>;
  deleteCredential(provider: CredentialProvider): Promise<CredentialStatusView>;
}

function validateIntent(intent: ResearchIntentInput): void {
  const length = Array.from(intent.prompt).length;
  if (length === 0 || length > MAX_PROMPT_CHARACTERS) {
    throw new Error(`Research prompt must contain 1-${MAX_PROMPT_CHARACTERS} characters.`);
  }
  if (intent.freshnessDays !== null && (intent.freshnessDays < 1 || intent.freshnessDays > 90)) {
    throw new Error("Freshness override must be 1-90 days.");
  }
  if (intent.maxResults !== null && (intent.maxResults < 1 || intent.maxResults > 10)) {
    throw new Error("Result-count override must be 1-10.");
  }
}

function validateIdentifier(value: string, field: string): void {
  if (!/^[0-9a-f-]{36}$/iu.test(value)) {
    throw new Error(`${field} is not a valid application-issued identifier.`);
  }
}

export const tauriBackend: BackendApi = {
  async getDiagnostics() {
    return invoke<DiagnosticsView>("get_diagnostics");
  },
  async setProjectBudget(hardBudgetMicroUsd) {
    if (!Number.isSafeInteger(hardBudgetMicroUsd) || hardBudgetMicroUsd < 500_000 || hardBudgetMicroUsd > 100_000_000) {
      throw new Error("Project budget must be between $0.50 and $100.00.");
    }
    await invoke<void>("set_project_budget", { input: { hardBudgetMicroUsd } });
  },
  async previewResearch(intent) {
    validateIntent(intent);
    return invoke<CostPreview>("preview_research", { intent });
  },
  async startResearch(intent, consentToken) {
    validateIntent(intent);
    validateIdentifier(consentToken, "consent token");
    return invoke<ResearchRunView>("start_research", { intent, consentToken });
  },
  async getResearchRun(jobId) {
    validateIdentifier(jobId, "job ID");
    return invoke<ResearchRunView>("get_research_run", { jobId });
  },
  async cancelResearch(jobId) {
    validateIdentifier(jobId, "job ID");
    return invoke<ResearchRunView>("cancel_research", { jobId });
  },
  async openEvidenceLink(linkHandle) {
    validateIdentifier(linkHandle, "link handle");
    await invoke<void>("open_evidence_link", { linkHandle });
  },
  async getCredentialStatus(provider) {
    return invoke<CredentialStatusView>("get_credential_status", { provider });
  },
  async storeCredential(provider, secret) {
    const bytes = new TextEncoder().encode(secret);
    if (bytes.length === 0 || bytes.length > MAX_SECRET_BYTES) {
      throw new Error(`Credential must contain 1-${MAX_SECRET_BYTES} UTF-8 bytes.`);
    }
    return invoke<CredentialStatusView>("store_credential", { provider, secret });
  },
  async validateCredential(provider) {
    return invoke<CredentialStatusView>("validate_credential", { provider });
  },
  async deleteCredential(provider) {
    return invoke<CredentialStatusView>("delete_credential", { provider });
  },
};
