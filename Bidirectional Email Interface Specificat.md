# Bidirectional Email Interface Specification

---

## Table of Contents

1. [Purpose](#1-purpose)
2. [Scope](#2-scope)
3. [Interface Objective](#3-interface-objective)
4. [Functional Requirements](#4-functional-requirements)
   - 4.1 [General Interface Requirements](#41-general-interface-requirements)
   - 4.2 [Endpoint Requirements](#42-endpoint-requirements)
   - 4.3 [Message Envelope Requirements](#43-message-envelope-requirements)
   - 4.4 [Message Type Requirements](#44-message-type-requirements)
   - 4.5 [Payload Handling Requirements](#45-payload-handling-requirements)
   - 4.6 [Email Mapping Requirements](#46-email-mapping-requirements)
     - 4.6.1 [Shared Mailbox and Endpoint Routing Requirements](#461-shared-mailbox-and-endpoint-routing-requirements)
   - 4.7 [Message Sending Requirements](#47-message-sending-requirements)
   - 4.8 [Message Reception Requirements](#48-message-reception-requirements)
   - 4.9 [ACK and NACK Requirements](#49-ack-and-nack-requirements)
   - 4.10 [Duplicate Detection and Idempotency](#410-duplicate-detection-and-idempotency-requirements)
   - 4.11 [Retry and Timeout Requirements](#411-retry-and-timeout-requirements)
   - 4.12 [State Management Requirements](#412-state-management-requirements)
   - 4.13 [Security Requirements](#413-security-requirements)
   - 4.14 [Protocol Versioning Requirements](#414-protocol-versioning-requirements)
   - 4.15 [Communication Health Monitoring](#415-communication-health-monitoring-requirements)
   - 4.16 [Logging and Audit Requirements](#416-logging-and-audit-requirements)
   - 4.17 [Error Handling Requirements](#417-error-handling-requirements)
   - 4.18 [Configuration Requirements](#418-configuration-requirements)
   - 4.19 [Extensibility Requirements](#419-extensibility-requirements)
5. [Functional Behavior Summary](#5-functional-behavior-summary)
6. [Architecture Overview](#6-architecture-overview)
7. [Data Flow Descriptions](#7-data-flow-descriptions)
8. [Error Condition Summary](#8-error-condition-summary)
9. [Security Summary](#9-security-summary)
10. [Maintainability Requirements](#10-maintainability-requirements)
11. [Design Rationale](#11-design-rationale)
12. [Design Principle](#12-design-principle)

---

## 1. Purpose

The purpose of this interface is to enable reliable, secure, bidirectional communication between **two or more servers** using email as the transport medium. The interface must remain independent of application-specific payload semantics so that future message contents can evolve without requiring redesign of the communication layer.

The interface shall support:

- Outbound message creation
- Inbound message reception
- Delivery state tracking
- Acknowledgement and negative acknowledgement handling
- Duplicate detection
- Retry and timeout handling
- Communication health monitoring

> This specification defines only the transport-level behavior and functional requirements of the email interface.

---

## 2. Scope

This specification covers the server-to-server email communication layer between two or more autonomous endpoints.

**It includes:**

- Message envelope rules
- Interface behavior
- Message identifiers
- Acknowledgement model
- State transitions
- Reliability requirements
- Security requirements
- Monitoring requirements
- Failure handling requirements

**It excludes:**

- Application payload structure
- Domain-specific message meaning
- Business logic processing
- UI requirements
- Storage implementation details beyond interface needs

---

## 3. Interface Objective

The interface shall provide a stable, implementation-independent transport contract over email such that:

- Either server can initiate communication
- Any participating server can send and receive structured transport messages
- The interface shall support two or more participating endpoints
- Message delivery outcomes can be inferred or confirmed
- Payload content can be changed later without changing the email transport layer

---

## 4. Functional Requirements

### 4.1 General Interface Requirements

| ID | Requirement |
|----|-------------|
| **FR-1** | The interface shall support bidirectional communication between two or more endpoints. The interface shall not be limited to exactly two servers. |
| **FR-2** | Each server shall be capable of acting both as: **sender** and **receiver**. |
| **FR-3** | The interface shall operate independently of the business payload definition. |
| **FR-4** | The interface shall separate: **transport metadata**, **control metadata**, and **payload content**. |
| **FR-5** | The interface shall allow future payload schemas to be introduced without changing the transport protocol. |
| **FR-6** | The interface shall support asynchronous communication. |
| **FR-7** | The interface shall tolerate variable transport latency inherent to email systems. |
| **FR-8** | The interface shall function without requiring persistent socket connectivity between the servers. |

### 4.2 Endpoint Requirements

| ID | Requirement |
|----|-------------|
| **FR-9** | Each server shall expose an email communication module responsible for: |
| | • Composing outbound transport messages |
| | • Sending outbound emails |
| | • Polling or reading inbound emails |
| | • Validating inbound messages |
| | • Generating acknowledgements |
| | • Handling retries |
| | • Updating message states |
| **FR-10** | Each server shall maintain a configurable list of one or more trusted peer endpoint identifiers. |
| **FR-11** | The interface shall reject messages from untrusted or unauthorized sender endpoint identifiers. |
| **FR-12** | Each server shall be identifiable by a unique endpoint identifier independent of its email address. |
| **FR-12a** | Each endpoint shall be capable of generating its own unique endpoint identifier autonomously at initial setup, without requiring coordination with other endpoints. The generated identifier shall be globally unique (e.g. UUID). |
| **FR-12b** | The interface shall support more than two endpoints participating in the communication network. Each endpoint shall be independently configured and identifiable. |
| **FR-12c** | Each endpoint shall maintain its own list of known peer endpoint identifiers. Because all endpoints share the same email account, the peer list contains only endpoint ID strings — not email addresses. |
| **FR-13** | The interface shall allow the shared email address to be changed without breaking logical endpoint identity, provided configuration is updated on all endpoints. |

### 4.3 Message Envelope Requirements

| ID | Requirement |
|----|-------------|
| **FR-14** | Every transport message shall contain a standardized envelope. |
| **FR-15** | The envelope shall include at minimum: |
| | • Protocol version |
| | • Message type |
| | • Message identifier |
| | • Correlation identifier (where applicable) |
| | • Sender endpoint identifier |
| | • Recipient endpoint identifier |
| | • Creation timestamp |
| | • Payload container |
| | • Integrity verification data |
| | • Optional security metadata |
| **FR-16** | The message identifier shall be globally unique. |
| **FR-17** | The interface shall support correlation between related messages through a correlation identifier. |
| **FR-18** | The envelope shall support transport control messages independently of business payload messages. |
| **FR-19** | The envelope shall support extension fields for future protocol evolution. |
| **FR-20** | Unknown optional envelope fields shall not cause rejection if core mandatory fields are valid. |

### 4.4 Message Type Requirements

The interface shall support at least the following transport-level message types:

| Type | Description |
|------|-------------|
| `DATA` | Carries application payload without the transport layer interpreting payload meaning. **(FR-22)** |
| `ACK` | Confirms receipt and acceptance of a referenced message at the transport/interface level. **(FR-23)** |
| `NACK` | Indicates receipt of a referenced message but failure to accept or process it at the interface level. **(FR-24)** |
| `HEARTBEAT` | Verifies communication path availability independently of business traffic. **(FR-25)** |
| `STATUS` | Allows reporting of transport-level state information when required. **(FR-26)** |
| `ERROR` | Communicates transport-level errors not adequately represented by ACK or NACK alone. **(FR-27)** |

> **FR-21:** All of the above message types shall be supported.

### 4.5 Payload Handling Requirements

| ID | Requirement |
|----|-------------|
| **FR-28** | The transport interface shall treat the payload as opaque data. |
| **FR-29** | The transport interface shall not impose business semantics on payload content. |
| **FR-30** | The interface shall permit payloads to be: |
| | • Plain structured text |
| | • Encoded binary content |
| | • Referenced attachment content |
| | • Future schema-defined objects |
| **FR-31** | The interface shall support payload absence for control-only messages. |
| **FR-32** | The interface shall permit a payload content type declaration. |
| **FR-33** | The interface shall permit future payload versioning independent of transport versioning. |

### 4.6 Email Mapping Requirements

| ID | Requirement |
|----|-------------|
| **FR-34** | Each transport message shall be encapsulated in one email message. |
| **FR-35** | The interface shall define a deterministic mapping between email fields and transport metadata. |
| **FR-36** | The email subject shall contain enough structured information to support initial filtering and routing. |
| **FR-37** | The email body shall contain the canonical transport message representation. |
| **FR-38** | The interface shall support optional file attachments where payload strategy later requires them. |
| **FR-39** | The interface shall not require attachments for normal control messaging. |
| **FR-40** | The interface shall be able to parse inbound transport messages regardless of ordinary mail client formatting differences, provided the canonical message section is intact. |
| **FR-41** | The interface shall ignore non-protocol email content outside the defined transport message container. |

#### 4.6.1 Shared Mailbox and Endpoint Routing Requirements

All endpoints in a BEIS deployment share a single email account. Endpoint identity is determined entirely by custom email headers and JSON body fields — not by email addresses.

| ID | Requirement |
|----|-------------|
| **FR-36a** | Every outbound email shall include an `X-BEIS-Sender` custom header whose value is the sender's endpoint identifier. |
| **FR-36b** | Every outbound email shall include an `X-BEIS-Recipient` custom header whose value is the intended recipient's endpoint identifier. |
| **FR-36c** | The email `From` and `To` fields shall both contain the shared email address. The email address itself carries no endpoint identity information. |
| **FR-36d** | The email subject line shall follow the structured format: `[BEIS] <sender_endpoint_id> -> <recipient_endpoint_id> <message_type> <message_id>`. This enables visual identification and basic filtering in standard email clients. |
| **FR-36e** | The JSON message body shall include `sender_endpoint_id` and `recipient_endpoint_id` fields that match the values in the corresponding custom headers. The receiver shall validate that header and body endpoint identifiers are consistent; mismatches shall be treated as a validation failure. |

### 4.7 Message Sending Requirements

| ID | Requirement |
|----|-------------|
| **FR-42** | The sender shall validate transport message completeness before sending. |
| **FR-43** | The sender shall assign a unique message identifier before dispatch. |
| **FR-44** | The sender shall store outbound message state before sending or immediately after sending in a way that prevents state loss. |
| **FR-45** | The sender shall mark each message with a transport state. |
| **FR-46** | Initial outbound message state shall be `CREATED` or equivalent. |
| **FR-47** | After successful submission to the local mail transfer mechanism, the state shall transition to `SENT` or equivalent. |
| **FR-48** | The sender shall await transport response for messages requiring acknowledgement. |
| **FR-49** | The sender shall support configurable acknowledgement timeout values. |
| **FR-50** | The sender shall support configurable retry policy for unacknowledged messages. |

### 4.8 Message Reception Requirements

| ID | Requirement |
|----|-------------|
| **FR-51** | The receiver shall poll or otherwise read inbound mailbox contents at a configurable interval. |
| **FR-52** | The receiver shall identify protocol-relevant emails using deterministic rules. |
| **FR-52a** | Because all endpoints share the same mailbox, the receiver shall filter inbound emails by inspecting the `X-BEIS-Recipient` header and processing only those messages where the header value matches the local endpoint identifier. Messages addressed to other endpoint identifiers shall be left in the mailbox untouched. |
| **FR-52b** | The receiver shall skip messages whose `X-BEIS-Sender` header matches the local endpoint identifier (self-sent messages). This prevents an endpoint from processing its own outbound messages. |
| **FR-52c** | Only messages that have been fully processed (accepted or rejected) by the local endpoint shall be deleted from the shared mailbox. Unprocessed messages and messages belonging to other endpoints shall never be deleted. |
| **FR-53** | The receiver shall validate: |
| | • Sender authorization (sender endpoint ID in trusted peer list) |
| | • Protocol version support |
| | • Mandatory fields |
| | • Message integrity |
| | • Message identifier format |
| | • Timestamp validity according to configured tolerance |
| | • Duplicate status |
| | • Header/body endpoint ID consistency (FR-36e) |
| **FR-54** | Invalid messages shall not be processed as valid transport messages. |
| **FR-55** | For invalid inbound protocol messages, the receiver shall generate a NACK or ERROR where feasible and safe. |
| **FR-56** | The receiver shall store inbound message state and processing result. |
| **FR-57** | The receiver shall separate transport acceptance from downstream business processing acceptance. |
| **FR-58** | Transport receipt shall be acknowledged independently of later business payload interpretation if such separation is configured. |

### 4.9 ACK and NACK Requirements

| ID | Requirement |
|----|-------------|
| **FR-59** | The interface shall support acknowledgement of a specific message by referencing its message identifier. |
| **FR-60** | ACK shall indicate that the referenced message was received and accepted at the transport/interface level. |
| **FR-61** | NACK shall indicate that the referenced message was received but rejected at the transport/interface level. |
| **FR-62** | NACK shall include a machine-readable reason code. |
| **FR-63** | NACK may include a human-readable diagnostic message. |
| **FR-64** | The interface shall define standard NACK reason categories at minimum for: |
| | • `MALFORMED_MESSAGE` |
| | • `UNAUTHORIZED_SENDER` |
| | • `UNSUPPORTED_VERSION` |
| | • `INTEGRITY_FAILURE` |
| | • `DUPLICATE_MESSAGE` |
| | • `EXPIRED_MESSAGE` |
| | • `INTERNAL_RECEIVER_FAILURE` |
| **FR-65** | ACK and NACK generation shall be deterministic and idempotent. |
| **FR-66** | The receiver shall not emit conflicting terminal responses for the same message unless explicitly defined by protocol rules. |
| **FR-67** | The sender shall correlate ACK and NACK responses to the original outbound message. |
| **FR-68** | Receipt of ACK shall move the message to an acknowledged state. |
| **FR-69** | Receipt of NACK shall move the message to a negatively acknowledged state. |

### 4.10 Duplicate Detection and Idempotency Requirements

| ID | Requirement |
|----|-------------|
| **FR-70** | The interface shall detect duplicate messages using the message identifier. |
| **FR-71** | Duplicate detection shall persist across service restarts. |
| **FR-72** | The receiver shall not process the same transport message as new more than once. |
| **FR-73** | The receiver shall respond to duplicate messages in a deterministic manner. |
| **FR-74** | The interface shall support idempotent re-delivery handling resulting from retries or delayed email transport. |
| **FR-75** | Duplicate detection behavior shall be configurable for retention duration. |

### 4.11 Retry and Timeout Requirements

| ID | Requirement |
|----|-------------|
| **FR-76** | The sender shall support retry when: |
| | • No ACK or NACK is received within timeout |
| | • Local sending fails transiently |
| | • Transport response is indeterminate |
| **FR-77** | Retry policy shall be configurable for: |
| | • Retry interval |
| | • Retry count |
| | • Escalation threshold |
| | • Message type applicability |
| **FR-78** | The interface shall distinguish between transient and terminal failure where determinable. |
| **FR-79** | Terminal failure shall stop further retries for the referenced message unless manually overridden. |
| **FR-80** | Exceeded retry limits shall place the message in `FAILED` state or equivalent. |
| **FR-81** | Retry attempts shall preserve the original message identifier or explicitly preserve correlation to the original message. |

### 4.12 State Management Requirements

| ID | Requirement |
|----|-------------|
| **FR-82** | The interface shall maintain transport-level message states. |
| **FR-85** | State transitions shall be deterministic. |
| **FR-86** | State transitions shall be auditable. |
| **FR-87** | The state model shall survive service restart without loss of message history required for transport correctness. |

**FR-83 — Outbound message states:**

```
CREATED → SENT → WAITING_FOR_ACK → ACKNOWLEDGED
                                  → NACKED
                → RETRY_PENDING   → (back to SENT)
                                  → FAILED
                                  → EXPIRED
```

| State | Description |
|-------|-------------|
| `CREATED` | Message constructed, not yet submitted |
| `SENT` | Successfully submitted to SMTP |
| `WAITING_FOR_ACK` | Awaiting ACK/NACK from receiver |
| `ACKNOWLEDGED` | ACK received — terminal success |
| `NACKED` | NACK received — terminal rejection |
| `RETRY_PENDING` | Timeout elapsed, retry scheduled |
| `FAILED` | Retry limit exceeded — terminal failure |
| `EXPIRED` | Message lifetime exceeded |

**FR-84 — Inbound message states:**

| State | Description |
|-------|-------------|
| `RECEIVED` | Email detected in mailbox |
| `VALIDATED` | Passed all validation checks |
| `ACCEPTED` | Accepted at transport level |
| `REJECTED` | Failed validation — NACK sent |
| `DUPLICATE` | Duplicate message detected |
| `RESPONSE_SENT` | ACK or NACK dispatched |

### 4.13 Security Requirements

| ID | Requirement |
|----|-------------|
| **FR-88** | The interface shall support sender authenticity verification. |
| **FR-89** | The interface shall support message integrity verification. |
| **FR-90** | The interface shall support confidentiality protection of transport messages. |
| **FR-91** | Security mechanisms shall be independent of payload semantics. |
| **FR-92** | The interface shall encrypt the entire transport message body using a shared symmetric encryption key before sending. The receiving endpoint shall decrypt the message body using the same shared key before processing. |
| **FR-92a** | The encryption algorithm shall be a well-established symmetric cipher (e.g. AES-256). The specific algorithm shall be configurable. |
| **FR-92b** | The shared encryption key shall be distributed to all participating endpoints as a key file stored on the local filesystem of each endpoint. |
| **FR-92c** | The key file path shall be specified in the endpoint configuration. |
| **FR-92d** | All endpoints that need to communicate with each other shall possess the same shared key file. Without the correct key file, an endpoint shall not be able to decrypt or send valid messages. |
| **FR-92e** | The interface shall reject and log any message that fails decryption. |
| **FR-93** | The interface shall support signature verification or equivalent authenticity validation. |
| **FR-94** | Messages failing required integrity or authenticity validation shall be rejected. |
| **FR-95** | Sensitive credentials and keys shall not be embedded in message payloads or email headers. The shared key shall only reside in the key file on disk and in memory during processing. |
| **FR-96** | Security configuration shall be externally manageable and rotatable without redesigning the protocol. |
| **FR-96a** | Key rotation shall be supported by replacing the key file on all endpoints. The interface shall support a configurable grace period during which both the old and new key may be accepted to allow rolling key updates across endpoints. |

#### 4.13.1 Key Generation Requirements

| ID | Requirement |
|----|-------------|
| **FR-96b** | The interface shall provide a key generation utility (keygen) capable of producing a valid shared symmetric encryption key file. |
| **FR-96c** | The keygen utility shall generate a cryptographically secure random key of sufficient length for the configured encryption algorithm (e.g. 256 bits for AES-256). |
| **FR-96d** | The keygen utility shall output the key to a file at a specified path. |
| **FR-96e** | The keygen utility shall be executable independently on any endpoint without requiring network access or coordination with other endpoints. |
| **FR-96f** | The generated key file shall be in a defined, stable binary or encoded format (e.g. raw bytes or base64-encoded) that all endpoints can read consistently. |
| **FR-96g** | The keygen utility shall not transmit the generated key over any network. Distribution of the key file to other endpoints is an out-of-band operational responsibility. |
| **FR-96h** | The keygen utility shall log key generation events (timestamp, output path, algorithm, key length) without logging the key material itself. |

### 4.14 Protocol Versioning Requirements

| ID | Requirement |
|----|-------------|
| **FR-97** | Every message shall declare a protocol version. |
| **FR-98** | The receiver shall validate protocol version compatibility. |
| **FR-99** | The interface shall support rejection of unsupported protocol versions. |
| **FR-100** | Unsupported versions shall result in a deterministic NACK or ERROR when feasible. |
| **FR-101** | The protocol shall support backward-compatible extension where possible. |

### 4.15 Communication Health Monitoring Requirements

| ID | Requirement |
|----|-------------|
| **FR-102** | The interface shall support periodic HEARTBEAT exchange between endpoints. |
| **FR-103** | HEARTBEAT frequency shall be configurable. |
| **FR-104** | HEARTBEAT response expectations shall be configurable. |
| **FR-105** | Absence of expected HEARTBEAT or other expected message activity beyond threshold shall mark the communication path degraded. |
| **FR-106** | Extended absence of expected communication shall mark the communication path failed. |
| **FR-107** | Communication health state shall be independently maintained from individual message states. |
| **FR-108** | Health states shall include at minimum: `HEALTHY`, `DEGRADED`, `FAILED`, `UNKNOWN`. |
| **FR-109** | The interface shall generate a communication-down event when thresholds are exceeded. |
| **FR-110** | The interface shall generate a communication-restored event when connectivity is re-established. |

### 4.16 Logging and Audit Requirements

| ID | Requirement |
|----|-------------|
| **FR-111** | The interface shall log all transport-level events relevant to traceability. |
| **FR-112** | Logged events shall include at minimum: |
| | • Message creation |
| | • Send attempt |
| | • Send success or failure |
| | • Inbound receipt |
| | • Validation result |
| | • ACK/NACK generation |
| | • Retry initiation |
| | • Timeout |
| | • State transition |
| | • Communication health transition |
| | • Encryption or decryption failure |
| | • Key file load or key file missing events |
| **FR-113** | Logs shall reference message identifiers and correlation identifiers where applicable. |
| **FR-114** | Logs shall avoid exposing protected payload data except where explicitly configured. |
| **FR-115** | The interface shall maintain sufficient audit data to reconstruct transport behavior for troubleshooting. |

### 4.17 Error Handling Requirements

| ID | Requirement |
|----|-------------|
| **FR-116** | The interface shall classify errors into at least: |
| | • Validation errors |
| | • Security errors |
| | • Encryption or decryption errors |
| | • Key file errors (missing, unreadable, invalid format) |
| | • Transport submission errors |
| | • Mailbox access errors |
| | • Parsing errors |
| | • Timeout errors |
| | • Internal processing errors |
| **FR-117** | Error classification shall be machine-readable. |
| **FR-118** | Recoverable and non-recoverable errors shall be distinguishable. |
| **FR-119** | Recoverable errors shall be eligible for retry according to policy. |
| **FR-120** | Non-recoverable errors shall produce terminal failure handling. |
| **FR-121** | The interface shall not silently discard protocol-relevant messages without logging the reason. |

### 4.18 Configuration Requirements

**FR-122** — The interface shall provide configurable parameters for:

| Parameter | Description |
|-----------|-------------|
| Endpoint identifier | This endpoint's unique ID |
| Own email address | Shared email address used by all endpoints for sending and receiving |
| Email credentials | Username, password, or application-specific token |
| SMTP settings | Host, port, encryption mode for outbound email |
| IMAP/POP3 settings | Host, port, encryption mode for inbound email |
| Peer endpoint identifiers | List of trusted peer endpoint ID strings (not email addresses — all peers share the same email account) |
| Mailbox connection settings | Connection pool, keep-alive, etc. |
| Polling interval | How often to check for inbound messages |
| Retry interval | Delay between retry attempts |
| Retry count | Maximum number of retries before failure |
| Acknowledgement timeout | How long to wait for ACK/NACK |
| Duplicate retention duration | How long to remember message IDs for duplicate detection |
| Heartbeat interval | Frequency of HEARTBEAT messages |
| Security mode | Encryption on/off, algorithm selection |
| Encryption algorithm | e.g. AES-256 |
| Shared encryption key file path | Path to the symmetric key file on disk |
| Key rotation grace period | Duration to accept both old and new keys |
| Accepted protocol versions | List of supported protocol versions |

| ID | Requirement |
|----|-------------|
| **FR-122a** | The configuration file shall store all email-related credentials and connection details required for the endpoint to send and receive email independently. |
| **FR-122b** | Credentials in the configuration file shall be protectable through encryption or environment variable references to avoid plaintext exposure. |
| **FR-123** | Configuration changes shall not require redesign of the message envelope. |
| **FR-124** | The interface shall support future addition of payload-specific configuration without changing transport configuration structure. |

### 4.19 Extensibility Requirements

| ID | Requirement |
|----|-------------|
| **FR-125** | The interface shall be designed so that future payload schemas can be inserted into the payload container without changing transport control logic. |
| **FR-126** | The interface shall support future introduction of new message types without breaking compliant implementations that do not use them. |
| **FR-127** | The interface shall support optional metadata extensions. |
| **FR-128** | The interface shall preserve transport compatibility when business payload evolves, provided core envelope rules remain unchanged. |

---

## 5. Functional Behavior Summary

At a functional level, the interface shall work as follows:

1. **Key Setup** — Before deployment, the keygen utility is used to generate a shared symmetric encryption key file. The key file is distributed out-of-band to all participating endpoints.
2. **Create** — A server creates a transport message with standard envelope metadata and opaque payload, addressed to a peer endpoint identifier.
3. **Encrypt & Send** — The message body is encrypted using the shared key. The email is sent from and to the **shared email address**, with `X-BEIS-Sender` and `X-BEIS-Recipient` custom headers identifying the logical sender and recipient endpoints.
4. **Receive & Decrypt** — The receiving server polls the shared mailbox, filters for messages where `X-BEIS-Recipient` matches its own endpoint ID, decrypts the message body using the shared key, validates it, and records its receipt. Messages addressed to other endpoints are left in the mailbox.
5. **Acknowledge** — The receiver returns an encrypted ACK or NACK referencing the original message (also routed through the shared mailbox with appropriate endpoint headers).
6. **Correlate** — The sender correlates the response and updates transport state.
7. **Retry or Fail** — If no response arrives within policy limits, the sender retries or marks failure.
8. **Monitor** — Heartbeat traffic independently monitors whether the communication path is functioning.

---

## 6. Architecture Overview

### 6.1 High-Level Architecture

Each endpoint shall be structured as an **independent, self-contained node**. No central server, broker, or coordinator exists. Every endpoint is an equal peer capable of sending and receiving.

The logical architecture of each endpoint shall consist of the following internal components:

| Component | Responsibility |
|-----------|---------------|
| **Outbound Module** | Message creation, envelope construction, encryption, and submission to the local SMTP transport. Sets `X-BEIS-Sender` and `X-BEIS-Recipient` custom headers. Sends from and to the shared email address. |
| **Inbound Module** | Shared mailbox polling, endpoint-level filtering by `X-BEIS-Recipient` header, self-sent message skipping, message detection, decryption, validation, header/body consistency check, and acknowledgement generation. Only deletes messages that this endpoint has fully processed. |
| **State Store** | Persisting outbound and inbound message states, duplicate detection records, and audit history. Must survive service restarts. |
| **Crypto Module** | Loading the shared key file, encrypting outbound message bodies, decrypting inbound message bodies, and integrity verification. |
| **Retry Scheduler** | Tracking unacknowledged messages, applying retry policy, and escalating to failure when limits are exceeded. |
| **Health Monitor** | Sending and evaluating HEARTBEAT messages and maintaining per-peer communication health state. |
| **Configuration Loader** | Reading endpoint configuration including email credentials, peer definitions, key file path, and all tunable parameters. |
| **Logger / Audit Trail** | Recording all transport-level events with message and correlation identifiers. |

### 6.2 Component Interaction

```
┌─────────────────────────────────────────────────────────┐
│                       ENDPOINT                          │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Config       │  │ Crypto       │  │ State         │  │
│  │ Loader       │  │ Module       │  │ Store         │  │
│  └──────┬───────┘  └──────┬───────┘  └───────┬───────┘  │
│         │                 │                  │          │
│  ┌──────▼─────────────────▼──────────────────▼───────┐  │
│  │             Outbound Module                       │  │
│  └─────────────────────┬─────────────────────────────┘  │
│                        │                                │
│                        ▼                                │
│                  [ SMTP Server ]                        │
│                                                         │
│                  [ IMAP / POP3 ]                        │
│                        │                                │
│                        ▼                                │
│  ┌─────────────────────┴─────────────────────────────┐  │
│  │             Inbound Module                        │  │
│  └──────┬──────────────┬──────────────────┬──────────┘  │
│         │              │                  │             │
│  ┌──────▼───────┐ ┌────▼─────────┐ ┌─────▼──────────┐  │
│  │ Retry        │ │ Health       │ │ Logger /       │  │
│  │ Scheduler    │ │ Monitor      │ │ Audit Trail    │  │
│  └──────────────┘ └──────────────┘ └────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**Outbound flow:** Configuration Loader → Outbound Module → Crypto Module → SMTP transport (To/From = shared email, endpoint IDs in `X-BEIS-*` headers) → State Store update.

**Inbound flow:** Shared IMAP/POP3 mailbox → Inbound Module (filter by `X-BEIS-Recipient`, skip self-sent) → Crypto Module → validation → State Store update → Outbound Module (for ACK/NACK).

**Retry flow:** Retry Scheduler reads from the State Store and triggers the Outbound Module for re-sends.

**Health flow:** Health Monitor operates independently, sending HEARTBEAT via the Outbound Module and evaluating responses from the Inbound Module.

### 6.3 Deployment Topology

Each endpoint runs independently. There is no shared database, no shared message queue, and no central coordination point. Endpoints discover each other only through **static configuration** (a peer list of endpoint identifiers). All endpoints share the **same email account** — the email address is a shared transport medium, not an identity mechanism. Endpoint identity is established exclusively through the `X-BEIS-Sender` and `X-BEIS-Recipient` custom headers and the matching JSON body fields. The shared encryption key file is the only other artifact that must be identical across communicating endpoints.

---

## 7. Data Flow Descriptions

### 7.1 Outbound Data Message Flow

1. Application layer requests the transport interface to send a `DATA` message with opaque payload to a specific peer endpoint identifier.
2. Outbound Module constructs the envelope (protocol version, message type, unique message ID, sender/recipient endpoint IDs, timestamp, payload container, integrity data).
3. State Store records the message in `CREATED` state.
4. Crypto Module encrypts the serialized transport message body using the shared key.
5. Outbound Module maps the encrypted body and metadata to email fields:
   - `From` and `To` are both set to the **shared email address**.
   - `X-BEIS-Sender` header is set to the local endpoint identifier.
   - `X-BEIS-Recipient` header is set to the target peer endpoint identifier.
   - Subject line follows the format: `[BEIS] <sender_id> -> <recipient_id> <type> <msg_id>`.
6. Email is submitted to the local SMTP server.
7. On successful submission, State Store transitions the message to `SENT`, then `WAITING_FOR_ACK`.
8. Retry Scheduler begins tracking the message for acknowledgement timeout.

### 7.2 Inbound Data Message Flow

1. Inbound Module polls the shared mailbox (IMAP/POP3) at the configured interval.
2. Emails matching protocol-relevant subject patterns are retrieved. The Inbound Module filters by `X-BEIS-Recipient` header, processing only messages addressed to the local endpoint identifier. Messages for other endpoints are left untouched.
3. Messages whose `X-BEIS-Sender` matches the local endpoint identifier are skipped (self-sent messages).
4. Crypto Module decrypts the email body using the shared key. On failure, the message is rejected and logged.
5. Inbound Module validates: sender authorization (sender endpoint ID in trusted peer list), protocol version, mandatory fields, integrity, message ID format, timestamp tolerance, duplicate status, and header/body endpoint ID consistency.
6. If valid, State Store records the message as `RECEIVED` → `VALIDATED` → `ACCEPTED`.
7. Outbound Module sends an encrypted ACK referencing the original message ID (routed via the shared mailbox with appropriate `X-BEIS-*` headers).
8. State Store records `RESPONSE_SENT` for the inbound message.
9. If invalid, the appropriate NACK or ERROR is generated and sent, and the message is recorded as `REJECTED`.
10. Only fully processed messages (accepted or rejected by this endpoint) are deleted from the shared mailbox.

### 7.3 ACK/NACK Correlation Flow

1. Inbound Module receives an ACK or NACK email.
2. After decryption and validation, the correlation identifier is extracted.
3. State Store looks up the original outbound message by message ID.
4. **For ACK:** message state transitions to `ACKNOWLEDGED`. Retry Scheduler stops tracking it.
5. **For NACK:** message state transitions to `NACKED`. Retry Scheduler stops tracking it. The NACK reason is recorded.

### 7.4 Retry Flow

1. Retry Scheduler detects that a message in `WAITING_FOR_ACK` has exceeded the acknowledgement timeout.
2. Message state transitions to `RETRY_PENDING`.
3. If retry count has not been exceeded, the Outbound Module re-sends the message (preserving the original message ID).
4. State transitions back to `SENT` → `WAITING_FOR_ACK`.
5. If retry count is exceeded, state transitions to `FAILED`. No further automatic retries occur.

### 7.5 Heartbeat Flow

1. Health Monitor sends a `HEARTBEAT` message to each configured peer at the configured interval via the Outbound Module.
2. The receiving endpoint's Inbound Module detects the HEARTBEAT, validates it, and returns an ACK.
3. The sending Health Monitor evaluates responses. If ACK is received, the peer is marked `HEALTHY`.
4. If no response within threshold, the peer is marked `DEGRADED`. If extended absence continues, the peer is marked `FAILED`.
5. When a previously failed peer responds again, the peer is marked `HEALTHY` and a communication-restored event is generated.

---

## 8. Error Condition Summary

The following summarizes the error conditions the interface must handle and the expected behavior for each.

### 8.1 Sending Errors

| Error Condition | Recoverable? | Behavior |
|-----------------|:------------:|----------|
| SMTP connection failure | ✅ Yes | Retry according to policy. Log the failure. |
| SMTP authentication failure | ❌ No | Mark `FAILED`. Log and alert. |
| Message construction error | ❌ No | Do not send. Log the error. |
| Encryption failure (key file missing or unreadable) | ❌ No | Do not send. Log and alert. |

### 8.2 Receiving Errors

| Error Condition | Recoverable? | Behavior |
|-----------------|:------------:|----------|
| Mailbox connection failure | ✅ Yes | Retry polling at next interval. Log the failure. |
| Mailbox authentication failure | ❌ No | Log and alert. Polling stops until resolved. |
| Decryption failure | ❌ No | Reject. Log. Do not send NACK (cannot verify sender identity). |
| Malformed envelope after decryption | ❌ No | Reject. Send NACK with `MALFORMED_MESSAGE`. |
| Header/body endpoint ID mismatch | ❌ No | Reject. Send NACK with `MALFORMED_MESSAGE`. Log the inconsistency. |
| Unauthorized sender endpoint ID | ❌ No | Reject. Send NACK with `UNAUTHORIZED_SENDER`. Sender endpoint ID not in trusted peer list. |
| Unsupported protocol version | ❌ No | Reject. Send NACK with `UNSUPPORTED_VERSION`. |
| Integrity check failure | ❌ No | Reject. Send NACK with `INTEGRITY_FAILURE`. |
| Duplicate message | — | Respond deterministically (re-send previous ACK/NACK). Log as duplicate. |
| Expired message (timestamp beyond tolerance) | ❌ No | Reject. Send NACK with `EXPIRED_MESSAGE`. |

### 8.3 Timeout Errors

| Error Condition | Recoverable? | Behavior |
|-----------------|:------------:|----------|
| ACK timeout | ✅ Yes | Trigger retry per policy. Log. |
| Heartbeat timeout | — | Degrades or fails peer health state. Log. |

### 8.4 Key and Configuration Errors

| Error Condition | Recoverable? | Behavior |
|-----------------|:------------:|----------|
| Key file not found at configured path | ❌ No | Endpoint cannot start or send/receive. Log and alert. |
| Key file format invalid | ❌ No | Endpoint cannot start. Log and alert. |
| Key mismatch (old key during rotation) | ⚠️ Grace | Handled by grace period. If expired, treated as decryption failure. |
| Configuration file missing or invalid | ❌ No | Endpoint cannot start. Log and alert. |

---

## 9. Security Summary

The security model is based on the following layers:

| Layer | Description |
|-------|-------------|
| **Confidentiality** | All transport message bodies are encrypted with a shared symmetric key (e.g. AES-256) before being placed in the email. Email content is opaque ciphertext to anyone without the key. |
| **Integrity** | The envelope includes integrity verification data. After decryption, the receiver validates that the message has not been tampered with. |
| **Authenticity** | Sender authorization is verified by checking the sender endpoint identifier against the trusted peer list. The shared key itself acts as an additional proof of membership in the trusted group. |
| **Key Management** | Keys are generated by the keygen utility, stored as files, and distributed out-of-band. Key rotation is supported with a configurable grace period. Keys are never transmitted within the protocol. |
| **Credential Protection** | Email credentials and key material are never included in protocol messages. Configuration supports encryption or environment variable references for stored credentials. |

---

## 10. Maintainability Requirements

### 10.1 Modularity

| ID | Requirement |
|----|-------------|
| **MR-1** | The implementation shall be structured into clearly separated modules corresponding to the components described in Section 6.1 (Outbound, Inbound, State Store, Crypto, Retry Scheduler, Health Monitor, Configuration Loader, Logger). |
| **MR-2** | Each module shall have a defined interface so that individual modules can be modified, replaced, or tested independently. |
| **MR-3** | The transport layer shall not contain business logic. Business payload processing is explicitly outside the transport module boundary. |

### 10.2 Testability

| ID | Requirement |
|----|-------------|
| **MR-4** | Each module shall be independently testable with mock or stub dependencies. |
| **MR-5** | The interface design shall support integration testing between two or more endpoints using test mailboxes and test key files. |
| **MR-6** | The State Store shall support inspection for test assertions (e.g. verifying state transitions, duplicate detection, retry counts). |

### 10.3 Configurability

| ID | Requirement |
|----|-------------|
| **MR-7** | All tunable parameters defined in Section 4.18 shall be modifiable without code changes. |
| **MR-8** | Configuration changes shall take effect on service restart at minimum. Hot-reload is optional but permitted. |

### 10.4 Upgrade and Deployment

| ID | Requirement |
|----|-------------|
| **MR-9** | Protocol versioning (Section 4.14) shall allow rolling upgrades where endpoints running different compatible versions can continue to communicate. |
| **MR-10** | Key rotation (FR-96a) shall allow rolling key updates without simultaneous downtime of all endpoints. |
| **MR-11** | New message types or envelope extensions shall not require changes to endpoints that do not use them (FR-126). |

### 10.5 Logging and Diagnostics

| ID | Requirement |
|----|-------------|
| **MR-12** | Logging (Section 4.16) shall provide sufficient information to diagnose any transport failure without requiring access to the raw email content. |
| **MR-13** | Log output format shall be structured (e.g. JSON) to support automated log analysis. |

---

## 11. Design Rationale

> *This section explains why the key design decisions in this specification were made, so that future maintainers and implementers understand the reasoning behind the interface.*

### 11.1 Why Email as Transport

Email was chosen because it works across network boundaries without requiring open inbound ports, VPN tunnels, or persistent connections between servers. It leverages existing infrastructure (SMTP/IMAP) that is universally available, operates asynchronously, and is inherently store-and-forward — which makes it resilient to temporary network outages. The tradeoff is higher latency compared to direct socket protocols, which the spec accommodates through configurable timeouts and polling intervals.

### 11.2 Why Shared Symmetric Key Instead of PKI

A shared symmetric key (e.g. AES-256) was chosen for simplicity and operational ease. It avoids the complexity of certificate management, certificate authorities, and key exchange protocols. For a known, closed group of endpoints that are configured manually, a single shared key distributed as a file is the simplest model that still provides strong encryption. The keygen utility and grace-period rotation support make key lifecycle manageable.

### 11.3 Why Polling Instead of Push

Email does not natively support server-push notification to external applications. IMAP IDLE exists but is not universally reliable across providers and adds connection management complexity. Polling at a configurable interval is the simplest, most portable, and most predictable approach. The polling interval is configurable so it can be tuned to balance responsiveness against mailbox load.

### 11.4 Why Explicit State Machines

Deterministic state transitions (Section 4.12) exist so that the system can always answer *"what happened to message X"* — even after crashes, restarts, or delayed email delivery. Without explicit states, race conditions between retries, late ACKs, and duplicates would be ambiguous. The state model makes retry logic, duplicate detection, and failure escalation predictable and auditable.

### 11.5 Why Opaque Payloads

The transport layer treats payloads as opaque (Sections 4.5, 6) so that business logic can evolve independently. If the transport layer understood payload meaning, every payload change would require transport layer changes. Keeping them separated means the transport spec is stable and the payload spec can be developed, versioned, and changed later without touching the communication layer.

### 11.6 Why Idempotent ACK/NACK

Email delivery can be unreliable — messages may arrive twice, or the same retry may trigger duplicate processing. Making ACK/NACK generation idempotent (FR-65) and duplicate detection persistent (FR-71) ensures that retries and delayed deliveries never cause contradictory state or double-processing. The system converges to the correct state regardless of how many times the same message arrives.

### 11.7 Why Independent Health Monitoring

Heartbeat traffic (Section 4.15) is separate from business messages so that communication path health can be assessed even when there is no business traffic. Without it, a long idle period would be indistinguishable from a communication failure. Independent health state allows operators to detect and react to connectivity problems proactively.

### 11.8 Why a Shared Mailbox

All endpoints in a BEIS deployment share a single email account rather than each endpoint having its own email address. This design decision was made for several reasons:

1. **Operational simplicity.** Provisioning and maintaining separate email accounts for every endpoint adds administrative burden that scales linearly with endpoint count. A single shared account means only one set of credentials to manage, one mailbox to monitor, and one set of SMTP/IMAP settings to configure.
2. **Decoupling identity from infrastructure.** Endpoint identity is a logical concept (a UUID or descriptive string), not an email address. By routing messages through custom headers (`X-BEIS-Sender`, `X-BEIS-Recipient`) and JSON body fields, the protocol ensures that endpoint identity survives email account migrations, provider changes, and credential rotations without any disruption to the logical communication topology.
3. **Multi-instance flexibility.** Multiple endpoint instances can run on the same machine (or different machines) without requiring separate email accounts. Each instance just needs a unique endpoint identifier and its own working directory.
4. **Simplified firewall and provider rules.** Only one email account needs to be allow-listed, configured for IMAP access, or granted app-specific passwords. This reduces the attack surface and the number of credentials in circulation.
5. **Consistent with the protocol's security model.** The shared symmetric encryption key already establishes a trust boundary — any entity with the key is a trusted participant. The shared mailbox aligns with this: all trusted endpoints can access the mailbox, and the `X-BEIS-Recipient` header ensures each endpoint only processes messages addressed to it.

---

## 12. Design Principle

> **The fundamental design principle of this interface is:**
>
> *The email transport layer shall define how messages are exchanged, verified, tracked, and acknowledged, but shall not define what the payload means.*
>
> That separation keeps the interface stable while allowing the payload specification to be developed later.
