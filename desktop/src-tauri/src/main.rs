fn main() {
    let arguments = std::env::args_os().skip(1).collect::<Vec<_>>();
    #[cfg(debug_assertions)]
    if arguments
        .first()
        .is_some_and(|value| value == "--m1-1-calibration-live")
    {
        if arguments.len() != 5 {
            eprintln!(
                "development M1.1 calibration requires database, resource, worker-temp, and new replay-fixture paths"
            );
            std::process::exit(2);
        }
        let result = ai_edit_machine_desktop_lib::run_m11_calibration_live(
            std::path::Path::new(&arguments[1]),
            std::path::Path::new(&arguments[2]),
            std::path::Path::new(&arguments[3]),
            std::path::Path::new(&arguments[4]),
        );
        match result {
            Ok(report) => match serde_json::to_string_pretty(&report) {
                Ok(value) => {
                    println!("{value}");
                    if !report.quality_target_met {
                        std::process::exit(3);
                    }
                }
                Err(_) => {
                    eprintln!("development M1.1 calibration report serialization failed safely");
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
    #[cfg(not(debug_assertions))]
    if arguments
        .first()
        .is_some_and(|value| value == "--m1-1-calibration-live")
    {
        eprintln!("the M1.1 calibration command is unavailable in production release builds");
        std::process::exit(2);
    }
    #[cfg(debug_assertions)]
    if arguments.first().is_some_and(|value| value == "--m1-provider-debug-live") {
        if arguments.len() != 5 {
            eprintln!("development provider debug requires database, resource, worker-temp, and new replay-fixture paths");
            std::process::exit(2);
        }
        let result = ai_edit_machine_desktop_lib::run_m1_provider_debug_live(
            std::path::Path::new(&arguments[1]),
            std::path::Path::new(&arguments[2]),
            std::path::Path::new(&arguments[3]),
            std::path::Path::new(&arguments[4]),
        );
        match result {
            Ok(report) => match serde_json::to_string_pretty(&report) {
                Ok(value) => {
                    println!("{value}");
                    if !report.valid_opportunity { std::process::exit(3); }
                },
                Err(_) => {
                    eprintln!("development provider-debug report serialization failed safely");
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
    #[cfg(not(debug_assertions))]
    if arguments.first().is_some_and(|value| value == "--m1-provider-debug-live") {
        eprintln!("the M1 provider-debug command is unavailable in production release builds");
        std::process::exit(2);
    }
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
