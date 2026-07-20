use reth_node_core::version::{
    RethCliVersionConsts, default_reth_version_metadata, try_init_version_metadata,
};
use std::borrow::Cow;

const SLOTSCAN_VERSION: &str = env!("CARGO_PKG_VERSION");
const SLOTSCAN_COMMIT: &str = match option_env!("SLOTSCAN_BUILD_COMMIT") {
    Some(commit) => commit,
    None => "unknown",
};

pub fn init() {
    try_init_version_metadata(slotscan_version_metadata(default_reth_version_metadata()))
        .expect("Reth version metadata must be initialized before the CLI is parsed");
}

fn slotscan_version_metadata(upstream: RethCliVersionConsts) -> RethCliVersionConsts {
    let short_version = format!("{SLOTSCAN_VERSION} (Reth {})", upstream.cargo_pkg_version);
    let long_version = format!(
        "Version: {SLOTSCAN_VERSION}\n\
         SlotScan Commit: {SLOTSCAN_COMMIT}\n\
         Reth Version: {}\n\
         Reth Commit: {}\n\
         Build Timestamp: {}\n\
         Build Features: {}\n\
         Build Profile: {}",
        upstream.cargo_pkg_version,
        upstream.vergen_git_sha_long,
        upstream.vergen_build_timestamp,
        upstream.vergen_cargo_features,
        upstream.build_profile_name,
    );

    RethCliVersionConsts {
        name_client: Cow::Borrowed("SlotScan Reth"),
        short_version: Cow::Owned(short_version),
        long_version: Cow::Owned(long_version),
        ..upstream
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn downstream_identity_preserves_upstream_protocol_metadata() {
        let upstream = RethCliVersionConsts {
            cargo_pkg_version: Cow::Borrowed("2.3.0"),
            vergen_git_sha_long: Cow::Borrowed("reth-commit"),
            vergen_build_timestamp: Cow::Borrowed("timestamp"),
            vergen_cargo_features: Cow::Borrowed("jemalloc,asm_keccak"),
            build_profile_name: Cow::Borrowed("maxperf"),
            p2p_client_version: Cow::Borrowed("reth/v2.3.0/target"),
            extra_data: Cow::Borrowed("reth/v2.3.0/linux"),
            ..Default::default()
        };

        let metadata = slotscan_version_metadata(upstream);

        assert_eq!(metadata.name_client, "SlotScan Reth");
        assert_eq!(metadata.cargo_pkg_version, "2.3.0");
        assert_eq!(metadata.p2p_client_version, "reth/v2.3.0/target");
        assert_eq!(metadata.extra_data, "reth/v2.3.0/linux");
        assert!(
            metadata
                .long_version
                .contains(&format!("Version: {SLOTSCAN_VERSION}"))
        );
        assert!(metadata.long_version.contains("Reth Version: 2.3.0"));
        assert!(metadata.long_version.contains("Build Profile: maxperf"));
    }
}
