

Blockchain Integration Module
Connects to a simulated Ethereum testnet (py-evm backend, equivalent to Ganache)
and deploys the Election Smart Contract using Web3.py
"""

import os
import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global singletons
# ---------------------------------------------------------------------------
_w3 = None
_contract = None
_admin_account = None
_contract_address = None
_abi = None

SOLC_VERSION = "0.8.0"
CONTRACT_SOURCE = Path(__file__).parent / "Election.sol"


def _compile_contract():
    """Compile Election.sol using py-solc-x and return (abi, bytecode)."""
    import solcx

    installed = solcx.get_installed_solc_versions()
    if not any(str(v) == SOLC_VERSION for v in installed):
        logger.info("Installing solc %s — this may take a moment on first run...", SOLC_VERSION)
        solcx.install_solc(SOLC_VERSION, show_progress=False)

    source_code = CONTRACT_SOURCE.read_text()
    compiled = solcx.compile_source(
        source_code,
        output_values=["abi", "bin"],
        solc_version=SOLC_VERSION,
    )
    contract_key = [k for k in compiled if "Election" in k][0]
    return compiled[contract_key]["abi"], compiled[contract_key]["bin"]


def init_blockchain():
    """
    Initialize the simulated blockchain environment:
      1. Start in-memory Ethereum testnet (PyEVM — equivalent to Ganache)
      2. Compile and deploy the Election smart contract
      3. Register default Nigerian presidential candidates
    Returns the deployed contract address.
    """
    global _w3, _contract, _admin_account, _contract_address, _abi

    if _contract is not None:
        return _contract_address

    logger.info("Initializing blockchain testnet (PyEVM)...")

    from web3 import Web3
    from eth_tester import EthereumTester, PyEVMBackend

    tester = EthereumTester(PyEVMBackend())
    _w3 = Web3(Web3.EthereumTesterProvider(tester))

    assert _w3.is_connected(), "Web3 failed to connect to testnet"
    _admin_account = _w3.eth.accounts[0]
    logger.info("Connected. Admin account: %s", _admin_account)

    _abi, bytecode = _compile_contract()

    ElectionContract = _w3.eth.contract(abi=_abi, bytecode=bytecode)
    tx_hash = ElectionContract.constructor("2023 Nigerian Presidential Election").transact(
        {"from": _admin_account, "gas": 3_000_000}
    )
    receipt = _w3.eth.get_transaction_receipt(tx_hash)
    _contract_address = receipt["contractAddress"]
    _contract = _w3.eth.contract(address=_contract_address, abi=_abi)
    logger.info("Contract deployed at: %s", _contract_address)

    # Default candidates
    for name, party, symbol in [
        ("Bola Ahmed Tinubu",    "APC",          "Elephant"),
        ("Atiku Abubakar",       "PDP",          "Umbrella"),
        ("Peter Obi",            "Labour Party", "Broom"),
        ("Rabiu Musa Kwankwaso", "NNPP",         "Sun"),
    ]:
        _contract.functions.addCandidate(name, party, symbol).transact(
            {"from": _admin_account, "gas": 300_000}
        )
    logger.info("Default candidates registered.")
    return _contract_address


# ---------------------------------------------------------------------------
# Cryptographic helpers
# ---------------------------------------------------------------------------

def compute_voter_hash(bvas_id: str, session_salt: str) -> bytes:
    """SHA-256(BVAS_ID + session_salt) → anonymized 32-byte voter identifier."""
    raw = f"{bvas_id}{session_salt}".encode("utf-8")
    return hashlib.sha256(raw).digest()


def compute_payload_hash(voter_choice: str, session_salt: str) -> str:
    """SHA-256(Voter_Choice + Session_Salt) — ballot payload hash for transparency."""
    raw = f"{voter_choice}{session_salt}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Voting
# ---------------------------------------------------------------------------

def cast_vote(bvas_id: str, candidate_id: int, session_salt: str) -> dict:
    voter_hash   = compute_voter_hash(bvas_id, session_salt)
    payload_hash = compute_payload_hash(str(candidate_id), session_salt)

    try:
        tx_hash = _contract.functions.castVote(voter_hash, candidate_id).transact(
            {"from": _admin_account, "gas": 500_000}
        )
        receipt = _w3.eth.get_transaction_receipt(tx_hash)
        if receipt.get("status") == 0:
            raise RuntimeError(f"REVERT: Transaction reverted on-chain (gasUsed={receipt['gasUsed']})")
        block   = _w3.eth.get_block(receipt["blockNumber"])
        return {
            "success":          True,
            "tx_hash":          tx_hash.hex() if isinstance(tx_hash, bytes) else str(tx_hash),
            "block_number":     receipt["blockNumber"],
            "block_hash":       block["hash"].hex(),
            "contract_address": _contract_address,
            "voter_hash":       voter_hash.hex(),
            "payload_hash":     payload_hash,
            "gas_used":         receipt["gasUsed"],
            "message":          "Transaction Successful: Vote Recorded",
        }
    except Exception as exc:
        err = str(exc)
        if "Duplicate" in err or "REVERT" in err:
            message = "Error: Unauthorized or Duplicate Vote"
        elif "not active" in err:
            message = "Error: That candidate is not currently active."
        else:
            message = f"Error: {err}"
        return {"success": False, "message": message}


def check_voter_status(bvas_id: str, session_salt: str) -> bool:
    voter_hash = compute_voter_hash(bvas_id, session_salt)
    return _contract.functions.checkVoterStatus(voter_hash).call()


# ---------------------------------------------------------------------------
# Candidate management
# ---------------------------------------------------------------------------

def get_candidates(include_disabled: bool = False) -> list:
    """Return candidates from the blockchain. By default filters out disabled ones."""
    count = _contract.functions.candidateCount().call()
    candidates = []
    for i in range(1, count + 1):
        cid, name, party, symbol, votes, disabled = _contract.functions.getCandidate(i).call()
        if not include_disabled and disabled:
            continue
        candidates.append({
            "id":       cid,
            "name":     name,
            "party":    party,
            "symbol":   symbol,
            "votes":    votes,
            "disabled": disabled,
        })
    return candidates


def get_all_candidates() -> list:
    """Return every candidate including disabled ones (for admin view)."""
    return get_candidates(include_disabled=True)


def add_candidate(name: str, party: str, symbol: str) -> dict:
    """Admin: add a new candidate to the smart contract."""
    try:
        tx_hash = _contract.functions.addCandidate(name, party, symbol).transact(
            {"from": _admin_account, "gas": 300_000}
        )
        _w3.eth.get_transaction_receipt(tx_hash)
        new_id = _contract.functions.candidateCount().call()
        logger.info("Candidate added: %s (%s) → ID %d", name, party, new_id)
        return {"success": True, "id": new_id}
    except Exception as exc:
        return {"success": False, "message": str(exc)}


def update_candidate(candidate_id: int, name: str, party: str, symbol: str) -> dict:
    """Admin: update an existing candidate's details on-chain."""
    try:
        tx_hash = _contract.functions.updateCandidate(candidate_id, name, party, symbol).transact(
            {"from": _admin_account, "gas": 300_000}
        )
        _w3.eth.get_transaction_receipt(tx_hash)
        logger.info("Candidate %d updated: %s (%s)", candidate_id, name, party)
        return {"success": True}
    except Exception as exc:
        return {"success": False, "message": str(exc)}


def toggle_candidate(candidate_id: int) -> dict:
    """Admin: enable or disable a candidate (hides them from the ballot)."""
    try:
        tx_hash = _contract.functions.toggleCandidate(candidate_id).transact(
            {"from": _admin_account, "gas": 100_000}
        )
        _w3.eth.get_transaction_receipt(tx_hash)
        _, _, _, _, _, disabled = _contract.functions.getCandidate(candidate_id).call()
        logger.info("Candidate %d toggled → disabled=%s", candidate_id, disabled)
        return {"success": True, "disabled": disabled}
    except Exception as exc:
        return {"success": False, "message": str(exc)}


# ---------------------------------------------------------------------------
# Election info
# ---------------------------------------------------------------------------

def get_election_status() -> dict:
    return {
        "is_open":          _contract.functions.electionOpen().call(),
        "total_votes":      _contract.functions.totalVotes().call(),
        "title":            _contract.functions.electionTitle().call(),
        "contract_address": _contract_address,
        "admin_account":    _admin_account,
        "block_number":     _w3.eth.block_number,
        "network":          "PyEVM Local Testnet (Simulated Ganache)",
        "chain_id":         _w3.eth.chain_id,
        "balance":          str(_w3.eth.get_balance(_admin_account)),
    }


def get_blockchain_transactions() -> list:
    count = _contract.functions.getTransactionCount().call()
    txs = []
    for i in range(count):
        voter_hash, candidate_id, timestamp, block_num = _contract.functions.voteTransactions(i).call()
        txs.append({
            "index":        i,
            "voter_hash":   voter_hash.hex() if isinstance(voter_hash, bytes) else voter_hash,
            "candidate_id": candidate_id,
            "timestamp":    timestamp,
            "block_number": block_num,
        })
    return txs


def toggle_election(open_election: bool) -> bool:
    if open_election:
        _contract.functions.reopenElection().transact({"from": _admin_account, "gas": 100_000})
    else:
        _contract.functions.closeElection().transact({"from": _admin_account, "gas": 100_000})
    return True


def get_w3():
    return _w3
