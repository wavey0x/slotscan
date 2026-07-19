mod inspector;
mod reth_adapter;
mod rpc;

use clap::Parser;
use reth_adapter::RethTraceAdapter;
use reth_ethereum::{
    cli::{chainspec::EthereumChainSpecParser, interface::Cli},
    node::EthereumNode,
};
use rpc::{SlotScanApiServer, SlotScanRpc};

fn main() {
    Cli::<EthereumChainSpecParser, Args>::parse()
        .run(async move |builder, _args| {
            let handle = builder
                .node(EthereumNode::default())
                .extend_rpc_modules(move |ctx| {
                    let adapter = RethTraceAdapter::new(ctx.registry.eth_api().clone());
                    ctx.modules
                        .merge_configured(SlotScanRpc::new(adapter).into_rpc())?;
                    Ok(())
                })
                .launch_with_debug_capabilities()
                .await?;

            handle.wait_for_node_exit().await
        })
        .unwrap();
}

#[derive(Debug, Clone, Copy, Default, clap::Args)]
struct Args {}
