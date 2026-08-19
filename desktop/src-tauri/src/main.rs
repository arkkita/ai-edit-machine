fn main() {
    let arguments = std::env::args_os().skip(1).collect::<Vec<_>>();
    if arguments.first().is_some_and(|value| value == "--openai-verifier-diagnostic") {
        if arguments.len() != 4 {
            eprintln!("verifier diagnostic requires database, resource, and worker-temp paths");
            std::process::exit(2);
        }
        let result = ai_edit_machine_desktop_lib::run_openai_verifier_diagnostic(
            std::path::Path::new(&arguments[1]),
            std::path::Path::new(&arguments[2]),
            std::path::Path::new(&arguments[3]),
        );
        match result {
            Ok(report) => match serde_json::to_string_pretty(&report) {
                Ok(value) => println!("{value}"),
                Err(_) => {
                    eprintln!("verifier diagnostic report serialization failed safely");
                    std::process::exit(2);
                }
            },
            Err(error) => {
                eprintln!("{error}");
                std::process::exit(2);
            }
        }
        return;
    }
    ai_edit_machine_desktop_lib::run();
}
