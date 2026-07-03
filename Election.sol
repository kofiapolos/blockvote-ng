// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/**
 * @title Election Smart Contract
 * @dev Blockchain Voting System for Nigeria - Final Year Project
 * @notice Immutable vote storage with candidate management and duplicate prevention
 */
contract Election {

    struct Candidate {
        uint id;
        string name;
        string party;
        string symbol;
        uint voteCount;
        bool disabled;
    }

    struct Transaction {
        bytes32 voterHash;
        uint candidateId;
        uint timestamp;
        uint blockNumber;
    }

    address public admin;
    bool public electionOpen;
    uint public candidateCount;
    uint public totalVotes;
    string public electionTitle;

    mapping(uint => Candidate) public candidates;
    mapping(bytes32 => bool) public hasVoted;
    Transaction[] public voteTransactions;

    event VoteCast(bytes32 indexed voterHash, uint indexed candidateId, uint timestamp, uint blockNumber);
    event CandidateAdded(uint indexed candidateId, string name, string party);
    event CandidateUpdated(uint indexed candidateId, string name, string party);
    event CandidateToggled(uint indexed candidateId, bool disabled);
    event ElectionStatusChanged(bool isOpen, uint timestamp);

    modifier onlyAdmin() {
        require(msg.sender == admin, "Access denied: Admin only");
        _;
    }

    modifier electionIsOpen() {
        require(electionOpen, "Election is currently closed");
        _;
    }

    modifier validCandidate(uint _id) {
        require(_id > 0 && _id <= candidateCount, "Invalid candidate ID");
        _;
    }

    constructor(string memory _title) {
        admin = msg.sender;
        electionOpen = true;
        totalVotes = 0;
        electionTitle = _title;
    }

    function addCandidate(
        string memory _name,
        string memory _party,
        string memory _symbol
    ) public onlyAdmin {
        candidateCount++;
        candidates[candidateCount] = Candidate(
            candidateCount,
            _name,
            _party,
            _symbol,
            0,
            false
        );
        emit CandidateAdded(candidateCount, _name, _party);
    }

    function updateCandidate(
        uint _id,
        string memory _name,
        string memory _party,
        string memory _symbol
    ) public onlyAdmin validCandidate(_id) {
        candidates[_id].name   = _name;
        candidates[_id].party  = _party;
        candidates[_id].symbol = _symbol;
        emit CandidateUpdated(_id, _name, _party);
    }

    function toggleCandidate(uint _id) public onlyAdmin validCandidate(_id) {
        candidates[_id].disabled = !candidates[_id].disabled;
        emit CandidateToggled(_id, candidates[_id].disabled);
    }

    /**
     * @dev Cast an anonymized vote using SHA-256 hashed voter identity
     * @param _voterHash SHA-256(BVAS_ID + session_salt) — anonymized
     * @param _candidateId The selected candidate's on-chain ID
     */
    function castVote(
        bytes32 _voterHash,
        uint _candidateId
    ) public electionIsOpen validCandidate(_candidateId) returns (bool) {
        require(!hasVoted[_voterHash], "REVERT: Unauthorized or Duplicate Vote");
        require(!candidates[_candidateId].disabled, "REVERT: Candidate is not active");

        hasVoted[_voterHash] = true;
        candidates[_candidateId].voteCount++;
        totalVotes++;

        voteTransactions.push(Transaction({
            voterHash:   _voterHash,
            candidateId: _candidateId,
            timestamp:   block.timestamp,
            blockNumber: block.number
        }));

        emit VoteCast(_voterHash, _candidateId, block.timestamp, block.number);
        return true;
    }

    function getCandidate(uint _id)
        public view validCandidate(_id)
        returns (uint, string memory, string memory, string memory, uint, bool)
    {
        Candidate memory c = candidates[_id];
        return (c.id, c.name, c.party, c.symbol, c.voteCount, c.disabled);
    }

    function checkVoterStatus(bytes32 _voterHash) public view returns (bool) {
        return hasVoted[_voterHash];
    }

    function getTransactionCount() public view returns (uint) {
        return voteTransactions.length;
    }

    function setTitle(string memory _title) public onlyAdmin {
        electionTitle = _title;
    }

    function closeElection() public onlyAdmin {
        require(electionOpen, "Election already closed");
        electionOpen = false;
        emit ElectionStatusChanged(false, block.timestamp);
    }

    function reopenElection() public onlyAdmin {
        electionOpen = true;
        emit ElectionStatusChanged(true, block.timestamp);
    }
}
