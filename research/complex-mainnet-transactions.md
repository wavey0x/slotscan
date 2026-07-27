# Complex Ethereum Mainnet Transactions

This is a reusable corpus of real Ethereum mainnet exploit transactions for
SlotScan conformance, performance, and limit testing. The incidents were sourced
from [DeFiHackLabs](https://github.com/SunWeb3Sec/DeFiHackLabs), their receipts
were verified on-chain, and the complete cases were replayed with
`slotscan_traceTransaction`.

The measurements below were collected on 2026-07-20 using SlotScan's production
trace limits:

- 5,000,000 EVM steps
- 10,000 ordered writes
- 20,000 SHA3 operations
- 5 MiB of captured preimages
- 100,000 observed storage slots

`Persistent writes` means ordered persistent write events, not distinct storage
slots. Multiple writes to the same slot are deliberately counted separately.
These are complexity measurements, not benchmark latency results; remeasure
latency for any performance claim.

## Recommended shortlist

| Need | Best starting case | Why |
| --- | --- | --- |
| Maximum write volume | Presale V5 | 3,257 ordered persistent writes |
| High write and SHA3 volume | Wise Lending | 2,128 writes and 9,158 SHA3 operations |
| SHA3/preimage pressure | Conic Finance ETH pool | 19,874 SHA3 operations, close to the configured limit |
| Storage-owner fanout | Cream Finance | 57 storage owners and 2.3 million EVM steps |
| Rollback semantics | Sturdy Finance | 32 reverted persistent write events |
| Trace-step degradation | Balancer V2 | Exceeds the 5,000,000-step detail limit |
| Non-step degradation | Miner NFT | Trips a detail limit below the step ceiling |

## Complete-trace cases

| Incident | EVM steps | Persistent writes | SHA3 operations | Storage owners | Transaction |
| --- | ---: | ---: | ---: | ---: | --- |
| Presale V5 | 3,227,339 | 3,257 | 5,902 | 6 | [`0x0ef0cde3d8348fdced3adf7d0475ec1364236dd6ab1d8580addad96b004b604a`](https://etherscan.io/tx/0x0ef0cde3d8348fdced3adf7d0475ec1364236dd6ab1d8580addad96b004b604a) |
| Wise Lending | 1,878,239 | 2,128 | 9,158 | 21 | [`0x04e16a79ff928db2fa88619cdd045cdfc7979a61d836c9c9e585b3d6f6d8bc31`](https://etherscan.io/tx/0x04e16a79ff928db2fa88619cdd045cdfc7979a61d836c9c9e585b3d6f6d8bc31) |
| Popsicle Finance | 788,288 | 1,827 | 1,930 | 30 | [`0xcd7dae143a4c0223349c16237ce4cd7696b1638d116a72755231ede872ab70fc`](https://etherscan.io/tx/0xcd7dae143a4c0223349c16237ce4cd7696b1638d116a72755231ede872ab70fc) |
| Sturdy Finance | 1,699,281 | 1,804 | 4,393 | 34 | [`0xeb87ebc0a18aca7d2a9ffcabf61aa69c9e8d3c6efade9e2303f8857717fb9eb7`](https://etherscan.io/tx/0xeb87ebc0a18aca7d2a9ffcabf61aa69c9e8d3c6efade9e2303f8857717fb9eb7) |
| Conic Finance ETH pool | 3,536,659 | 1,703 | 19,874 | 33 | [`0x37acd17a80a5f95728459bfea85cb2e1f64b4c75cf4a4c8dcb61964e26860882`](https://etherscan.io/tx/0x37acd17a80a5f95728459bfea85cb2e1f64b4c75cf4a4c8dcb61964e26860882) |
| Curve Vyper exploit | 2,346,457 | 1,297 | 319 | 6 | [`0x2e7dc8b2fb7e25fd00ed9565dcc0ad4546363171d5e00f196d48103983ae477c`](https://etherscan.io/tx/0x2e7dc8b2fb7e25fd00ed9565dcc0ad4546363171d5e00f196d48103983ae477c) |
| MIM / Abracadabra | 1,879,306 | 1,183 | 2,928 | 16 | [`0x26a83db7e28838dd9fee6fb7314ae58dcc6aee9a20bf224c386ff5e80f7e4cf2`](https://etherscan.io/tx/0x26a83db7e28838dd9fee6fb7314ae58dcc6aee9a20bf224c386ff5e80f7e4cf2) |
| Indexed Finance | 923,160 | 929 | 2,619 | 20 | [`0x44aad3b853866468161735496a5d9cc961ce5aa872924c5d78673076b1cd95aa`](https://etherscan.io/tx/0x44aad3b853866468161735496a5d9cc961ce5aa872924c5d78673076b1cd95aa) |
| Onyx Protocol | 1,366,191 | 780 | 2,497 | 32 | [`0xf7c21600452939a81b599017ee24ee0dfd92aaaccd0a55d02819a7658a6ef635`](https://etherscan.io/tx/0xf7c21600452939a81b599017ee24ee0dfd92aaaccd0a55d02819a7658a6ef635) |
| bZx | 694,396 | 759 | 2,389 | 40 | [`0xb072f2e88058c147d8ff643694b43a42e36525b7173ce1daf76e6c06170b0e77`](https://etherscan.io/tx/0xb072f2e88058c147d8ff643694b43a42e36525b7173ce1daf76e6c06170b0e77) |
| KyberSwap Elastic | 2,540,050 | 705 | 885 | 16 | [`0x485e08dc2b6a4b3aeadcb89c3d18a37666dc7d9424961a2091d6b3696792f0f3`](https://etherscan.io/tx/0x485e08dc2b6a4b3aeadcb89c3d18a37666dc7d9424961a2091d6b3696792f0f3) |
| Yearn yDAI | 961,804 | 633 | 1,897 | 19 | [`0x59faab5a1911618064f1ffa1e4649d85c99cfd9f0d64dcebbc1af7d7630da98b`](https://etherscan.io/tx/0x59faab5a1911618064f1ffa1e4649d85c99cfd9f0d64dcebbc1af7d7630da98b) |
| Pickle Finance | 331,067 | 627 | 1,078 | 8 | [`0xe72d4e7ba9b5af0cf2a8cfb1e30fd9f388df0ab3da79790be842bfbed11087b0`](https://etherscan.io/tx/0xe72d4e7ba9b5af0cf2a8cfb1e30fd9f388df0ab3da79790be842bfbed11087b0) |
| Cream Finance | 2,324,323 | 511 | 6,194 | 57 | [`0x0fe2542079644e107cbf13690eb9c2c65963ccb79089ff96bfaf8dced2331c92`](https://etherscan.io/tx/0x0fe2542079644e107cbf13690eb9c2c65963ccb79089ff96bfaf8dced2331c92) |
| Beanstalk | 405,225 | 495 | 769 | 22 | [`0xcd314668aaa9bbfebaf1a0bd2b6553d01dd58899c508d4729fa7311dc5d33ad7`](https://etherscan.io/tx/0xcd314668aaa9bbfebaf1a0bd2b6553d01dd58899c508d4729fa7311dc5d33ad7) |

Useful distinguishing facts:

- Presale V5 has the largest ordered write stream in this set.
- Conic Finance comes within 126 operations of the configured SHA3 ceiling.
- Cream Finance has the greatest storage-owner fanout.
- Sturdy Finance includes 32 reverted persistent write events.

## Intentional degradation cases

These transactions should retain the authoritative prestate diff while
discarding incomplete detailed evidence and returning `trace_limit`.

| Incident | Observed scale | Expected result | Transaction |
| --- | --- | --- | --- |
| Balancer V2 | 6,080,320 EVM steps | Exceeds the 5,000,000-step limit | [`0x6ed07db1a9fe5c0794d44cd36081d6a6df103fab868cdd75d581e3bd23bc9742`](https://etherscan.io/tx/0x6ed07db1a9fe5c0794d44cd36081d6a6df103fab868cdd75d581e3bd23bc9742) |
| Miner NFT | 2,098,705 EVM steps and 4,003 receipt logs | Trips a non-step trace-detail limit | [`0x75e3aeb00df69882a1b15d424e5e642650326ca3b923d7fd1922d57c51bc2c78`](https://etherscan.io/tx/0x75e3aeb00df69882a1b15d424e5e642650326ca3b923d7fd1922d57c51bc2c78) |

## Usage guidance

- Keep benchmark claims separate from these complexity measurements.
- Verify the receipt block hash before adding a transaction to a pinned corpus.
- Require exact legacy/native semantic parity before comparing latency.
- Use complete cases to test evidence volume and the degradation cases to test
  honest limit behavior.
- Add a transaction only when it contributes a new semantic or complexity axis,
  or preserves a real regression.
