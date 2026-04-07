#!/usr/bin/env python3
"""
Test that removeForReorg correctly handles BIP68 transactions with
mempool parents after invalidateblock.

Previously, transactions with nSequence=0 (BIP68 enabled, relative
locktime 0) and mempool parents were incorrectly removed because
TestLockPointValidity used stale cached LockPoints with a genesis
sentinel for maxInputBlock.

See issue #35007 for details.
"""

from test_framework.test_framework import BitcoinTestFramework
from test_framework.wallet import MiniWallet
from test_framework.messages import (
    CTransaction, CTxIn, CTxOut, COutPoint, CTxInWitness, COIN,
)
from test_framework.script import CScript, OP_RETURN

SEQ_BIP68_DISABLE = 0xFFFFFFFE
SEQ_BIP68_ZERO = 0x00000000


class MempoolReorgBip68StaleLocksTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 1
        self.setup_clean_chain = True
        self.extra_args = [["-maxmempool=999"]]

    def run_test(self):
        node = self.nodes[0]
        self.wallet = MiniWallet(node)
        self.generate(self.wallet, 200)

        # Confirm funding tx outside the reorg window
        funding = self.wallet.send_self_transfer_multi(
            from_node=node, num_outputs=2, confirmed_only=True,
        )
        block_setup = self.generate(node, 1)[0]
        self.wallet.rescan_utxos(include_mempool=True)

        H = node.getblockcount()
        self.log.info(f"Setup complete at height H={H}")

        # Create parent txs (confirmed inputs) and child txs (mempool parents)
        parent_A = self.wallet.send_self_transfer(
            from_node=node, utxo_to_spend=funding["new_utxos"][0],
        )
        parent_B = self.wallet.send_self_transfer(
            from_node=node, utxo_to_spend=funding["new_utxos"][1],
        )
        child_A = self.wallet.send_self_transfer(
            from_node=node,
            utxo_to_spend=parent_A["new_utxo"],
            sequence=SEQ_BIP68_DISABLE,
        )
        child_B = self.wallet.send_self_transfer(
            from_node=node,
            utxo_to_spend=parent_B["new_utxo"],
            sequence=SEQ_BIP68_ZERO,
        )

        self.log.info(f"child_A (seq=0xFFFFFFFE, BIP68 off): {child_A['txid'][:16]}")
        self.log.info(f"child_B (seq=0x00000000, BIP68 on):  {child_B['txid'][:16]}")

        # Mine empty block (txs stay in mempool)
        block_Y = self.generateblock(
            node, output=self.wallet.get_address(), transactions=[],
        )["hash"]

        # Invalidate both blocks
        node.invalidateblock(block_Y)
        node.invalidateblock(block_setup)
        assert node.getblockcount() == H - 1

        mp = node.getrawmempool()

        # Both children must survive — the fix recalculates stale LockPoints
        assert child_A["txid"] in mp, "child_A (BIP68 disabled) must survive"
        assert child_B["txid"] in mp, "child_B (BIP68 enabled) must survive after fix"

        self.log.info(f"child_A (BIP68 disabled): SURVIVED")
        self.log.info(f"child_B (BIP68 enabled):  SURVIVED (stale lockpoints recalculated)")
        self.log.info("PASS: removeForReorg correctly recalculates BIP68 lockpoints")


if __name__ == "__main__":
    MempoolReorgBip68StaleLocksTest(__file__).main()
