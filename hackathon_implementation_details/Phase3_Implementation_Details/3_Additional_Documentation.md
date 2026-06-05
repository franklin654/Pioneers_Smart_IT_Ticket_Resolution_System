# Additional Design Documentation
## AI Powered Intelligent Ticket Routing & Resolution Agent

**Version:** 2.0 - Design Focus  
**Date:** 2026  
**Classification:** Hackathon Round 2 Documentation

---

## Table of Contents

1. [API Design Specifications](#1-api-design-specifications)
2. [Design Constraints & Assumptions](#2-design-constraints--assumptions)
3. [Testing Strategy](#3-testing-strategy)
4. [Security Design](#4-security-design)
5. [Performance Requirements](#5-performance-requirements)
6. [Monitoring & Observability Design](#6-monitoring--observability-design)

---

## 1. API DESIGN SPECIFICATIONS

### 1.1 RESTful API Design Principles

**Design Philosophy:**
- **Resource-oriented:** URLs represent resources, not actions
- **Stateless:** Each request contains all necessary context
- **HTTP semantics:** Use appropriate verbs (GET, POST, PUT, DELETE)
- **Versioned:** API version in URL path (/api/v1, /api/v2)
- **JSON-first:** Request and response bodies in JSON
- **Hypermedia:** Include links to related resources (HATEOAS-light)

**URL Structure Convention:**
```
https://{domain}/api/{version}/{resource}/{identifier}/{sub-resource}

Examples:
  GET  /api/v1/tickets/TKT-12345
  POST /api/v1/tickets
  GET  /api/v1/tickets/TKT-12345/resolutions
  POST /api/v1/resolutions/123/feedback
```

---

### 1.2 Core API Endpoints Specification

#### Endpoint: POST /api/v1/tickets/ingest

**Purpose:** Create new ticket in system

**Request Schema (JSON Schema):**
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["ticket_id", "title", "description", "priority"],
  "properties": {
    "ticket_id": {
      "type": "string",
      "pattern": "^[A-Z]+-\\d+$",
      "minLength": 5,
      "maxLength": 50,
      "description": "Unique identifier from source system"
    },
    "title": {
      "type": "string",
      "minLength": 10,
      "maxLength": 200,
      "description": "Brief summary of issue"
    },
    "description": {
      "type": "string",
      "minLength": 50,
      "maxLength": 5000,
      "description": "Detailed description of issue"
    },
    "category": {
      "type": "string",
      "enum": ["Infrastructure", "Application", "Security", "Database", "Access Management", "Network"],
      "description": "Optional pre-classification"
    },
    "priority": {
      "type": "string",
      "enum": ["Low", "Medium", "High", "Critical"],
      "description": "Business priority"
    },
    "source": {
      "type": "string",
      "enum": ["servicenow", "jira", "manual", "csv", "api"],
      "default": "api",
      "description": "Source system"
    },
    "source_id": {
      "type": "string",
      "description": "ID in source system"
    }
  }
}
```

**Response Schema (Success - 201 Created):**
```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "integer",
      "description": "Internal database ID"
    },
    "ticket_id": {
      "type": "string",
      "description": "Echoed from request"
    },
    "status": {
      "type": "string",
      "enum": ["ingested"],
      "description": "Initial state"
    },
    "estimated_resolution_time": {
      "type": "string",
      "description": "Human-readable estimate (e.g., '< 2 hours')"
    },
    "created_at": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 timestamp"
    },
    "_links": {
      "type": "object",
      "properties": {
        "self": {"type": "string", "format": "uri"},
        "status": {"type": "string", "format": "uri"}
      }
    }
  }
}
```

**Error Response Schemas:**
```json
{
  "400 Bad Request": {
    "error": "string (error type)",
    "message": "string (human-readable)",
    "details": [
      {
        "field": "string (field name)",
        "issue": "string (validation issue)"
      }
    ]
  },
  "409 Conflict": {
    "error": "duplicate_ticket",
    "message": "Ticket with ID {ticket_id} already exists",
    "existing_ticket_id": "integer",
    "created_at": "string (ISO 8601)"
  },
  "429 Too Many Requests": {
    "error": "rate_limit_exceeded",
    "message": "Rate limit of {limit} req/min exceeded",
    "retry_after": "integer (seconds)"
  }
}
```

---

#### Endpoint: GET /api/v1/tickets/{ticket_id}

**Purpose:** Retrieve complete ticket information

**Path Parameters:**
- `ticket_id`: string, ticket identifier (e.g., "TKT-12345")

**Response Schema (Success - 200 OK):**
```json
{
  "type": "object",
  "properties": {
    "id": "integer",
    "ticket_id": "string",
    "title": "string",
    "description": "string",
    "category": "string",
    "priority": "enum",
    "status": {
      "type": "string",
      "enum": ["new", "classifying", "classified", "retrieving", "generating", 
               "evaluating", "auto_resolved", "assigned", "escalated", 
               "in_progress", "resolved", "closed", "reopened"]
    },
    "confidence_score": {
      "type": "number",
      "minimum": 0,
      "maximum": 1,
      "description": "Classification confidence"
    },
    "routing_path": {
      "type": "string",
      "enum": ["auto_resolved", "assigned", "escalated"]
    },
    "classification": {
      "type": "object",
      "properties": {
        "category": "string",
        "confidence": "number (0.0-1.0)",
        "is_multi_domain": "boolean",
        "probabilities": {
          "type": "object",
          "description": "Map of category to probability"
        },
        "classified_at": "string (ISO 8601)"
      }
    },
    "resolution": {
      "type": "object",
      "properties": {
        "resolution_text": "string",
        "resolution_steps": {
          "type": "array",
          "items": {"type": "string"}
        },
        "sources": {
          "type": "array",
          "items": {"type": "string"},
          "description": "Source ticket IDs used in RAG"
        },
        "created_at": "string (ISO 8601)",
        "created_by": {
          "type": "string",
          "enum": ["auto", "human"]
        }
      }
    },
    "evaluation": {
      "type": "object",
      "properties": {
        "relevance_score": {"type": "integer", "minimum": 1, "maximum": 5},
        "completeness_score": {"type": "integer", "minimum": 1, "maximum": 5},
        "actionability_score": {"type": "integer", "minimum": 1, "maximum": 5},
        "avg_score": {"type": "number"},
        "evaluated_at": "string (ISO 8601)"
      }
    },
    "created_at": "string (ISO 8601)",
    "updated_at": "string (ISO 8601)",
    "resolved_at": "string (ISO 8601) or null",
    "_links": {
      "type": "object",
      "properties": {
        "self": "string (URI)",
        "status": "string (URI)",
        "feedback": "string (URI)"
      }
    }
  }
}
```

---

#### Endpoint: POST /api/v1/resolutions/{resolution_id}/feedback

**Purpose:** Submit human feedback on generated resolution

**Path Parameters:**
- `resolution_id`: integer, resolution identifier

**Request Schema:**
```json
{
  "type": "object",
  "required": ["feedback_type", "reviewed_by"],
  "properties": {
    "feedback_type": {
      "type": "string",
      "enum": ["accepted", "rejected", "modified"],
      "description": "Whether resolution worked"
    },
    "rating": {
      "type": "integer",
      "minimum": 1,
      "maximum": 5,
      "description": "Optional quality rating"
    },
    "comments": {
      "type": "string",
      "maxLength": 1000,
      "description": "Optional feedback comments"
    },
    "reviewed_by": {
      "type": "string",
      "format": "email",
      "description": "Email of reviewer"
    },
    "modified_resolution": {
      "type": "string",
      "description": "If type=modified, the corrected resolution"
    }
  }
}
```

**Response Schema (Success - 200 OK):**
```json
{
  "type": "object",
  "properties": {
    "status": {"type": "string", "enum": ["feedback_recorded"]},
    "feedback_id": "integer",
    "kb_updated": {
      "type": "boolean",
      "description": "Whether resolution was added to knowledge base"
    }
  }
}
```

---

### 1.3 WebSocket API Specification

**Purpose:** Real-time ticket status updates

**Connection Protocol:**
```
Protocol: WebSocket (RFC 6455)
Endpoint: wss://{domain}/ws/tickets/{ticket_id}
Subprotocol: ticket-updates-v1
Authentication: JWT token in Sec-WebSocket-Protocol header
```

**Connection Flow:**
1. Client initiates WebSocket handshake with JWT
2. Server validates JWT and returns 101 Switching Protocols
3. Server sends initial state message
4. Server sends updates on state changes
5. Client can send ping frames for keep-alive
6. Either party can close connection

**Message Format (Server → Client):**
```json
{
  "type": "object",
  "required": ["event", "ticket_id", "timestamp"],
  "properties": {
    "event": {
      "type": "string",
      "enum": ["status_change", "agent_message", "resolution_generated", "routing_decision", "error"]
    },
    "ticket_id": "string",
    "from_status": "string (optional, for status_change)",
    "to_status": "string (optional, for status_change)",
    "data": {
      "type": "object",
      "description": "Event-specific payload"
    },
    "timestamp": "string (ISO 8601)"
  }
}
```

**Event Types & Payloads:**

| Event | Payload | Description |
|-------|---------|-------------|
| `status_change` | `{from_status, to_status, reason}` | Ticket state transition |
| `agent_message` | `{agent, message, intent}` | Agent posted message |
| `resolution_generated` | `{resolution_steps[], sources[]}` | Resolution created |
| `routing_decision` | `{path, confidence, assigned_to}` | Routing determined |
| `error` | `{error_code, message}` | Processing error |

**Heartbeat Mechanism:**
- Server sends ping frame every 30 seconds
- Client must respond with pong within 10 seconds
- Connection closed if 3 consecutive pongs missed

---

### 1.4 API Versioning Strategy

**Version Format:** `/api/v{major}`

**Versioning Rules:**
- **Major version** incremented for breaking changes
  - Changed response structure
  - Removed fields
  - Changed semantics
- **Minor version** (not in URL) for backward-compatible additions
  - New optional fields
  - New endpoints
- **Patch version** for bug fixes (not exposed)

**Deprecation Policy:**
- Old versions supported for 6 months after new version release
- Deprecation warnings in response headers:
  ```
  Deprecation: date="2026-12-31"
  Sunset: date="2025-06-30"
  Link: <https://docs.api.com/migration-guide>; rel="deprecation"
  ```

---

## 2. DESIGN CONSTRAINTS & ASSUMPTIONS

### 2.1 System Constraints

**Performance Constraints:**
- End-to-end latency must be < 5 seconds (99th percentile)
- API response time must be < 440ms (synchronous portion)
- System must support 10,000 tickets/day sustained load
- Database queries must complete in < 50ms (95th percentile)

**Resource Constraints:**
- GPU memory: 16GB minimum for Mistral-7B inference
- RAM: 16GB minimum, 32GB recommended
- Storage: 500GB minimum, 2TB recommended for 1-year retention
- Network: 1 Gbps minimum for internal communication

**Scalability Constraints:**
- Horizontal scaling for stateless services (API, workers)
- Vertical scaling for database (until 10M tickets)
- GPU scaling for LLM (1 GPU per 100 concurrent inferences)

---

### 2.2 Design Assumptions

**Data Assumptions:**
- Average ticket description: 300 words (1500 characters)
- Ticket volume: 5,000-10,000 per day
- Ticket categories distribution: Relatively balanced (no category > 40%)
- Resolution quality feedback rate: 20% of resolved tickets

**User Behavior Assumptions:**
- Peak hours: 9am-5pm weekdays (3x average load)
- Ticket submission pattern: Burst during incidents
- Human review time: < 5 minutes for auto-resolve confirmations
- Feedback provided within 24 hours of resolution

**Environment Assumptions:**
- Deployment: Private cloud or on-premises datacenter
- Network: Reliable, low-latency internal network
- GPU availability: NVIDIA V100/A100 or equivalent
- Internet: Available for model downloads (one-time)

**Integration Assumptions:**
- ITSM systems support webhook push
- Authentication: Existing OAuth 2.0 provider available
- User directory: LDAP/AD available for user lookup

---

### 2.3 Non-Functional Requirements

#### Availability
- **Target:** 99.5% uptime (3.65 hours downtime/month)
- **Measurement:** Uptime monitoring with 1-minute granularity
- **Acceptable downtime:** Planned maintenance windows (2am-4am weekends)

#### Reliability
- **Data durability:** 99.999% (no ticket loss)
- **Data consistency:** Strong consistency for ticket state
- **Error rate:** < 0.1% of requests fail
- **Recovery time:** < 15 minutes for service restart

#### Maintainability
- **Code quality:** 80% test coverage minimum
- **Documentation:** All APIs documented with OpenAPI
- **Logging:** Structured logs for all errors and state changes
- **Monitoring:** Metrics for all key operations

#### Usability
- **API response clarity:** Error messages must be actionable
- **Dashboard intuitiveness:** < 5 minutes to understand system status
- **Deployment simplicity:** One-command deployment for development

---

## 3. TESTING STRATEGY

### 3.1 Unit Testing Strategy

**Scope:** Individual functions and classes in isolation

**Components to Test:**

| Component | Test Focus | Success Criteria |
|-----------|------------|------------------|
| **Schema Validator** | Edge cases, malformed input | 100% validation coverage |
| **PII Masker** | Entity detection accuracy | F1 > 0.95 on test set |
| **Embedding Generator** | Determinism, dimension | Same input → same output |
| **Classifier** | Prediction accuracy | F1 ≥ 0.92 on test set |
| **Retriever** | Relevance of results | MRR > 0.8 on test queries |
| **LLM Prompt Builder** | Correct formatting | No syntax errors |
| **Router** | Decision logic | 100% path coverage |

**Test Data Requirements:**
- Minimum 100 test cases per component
- Include edge cases (empty strings, max length, special characters)
- Include domain-specific examples (actual ticket text)

**Mocking Strategy:**
- Mock external dependencies (database, LLM)
- Mock time for timestamp testing
- Mock random for deterministic tests

---

### 3.2 Integration Testing Strategy

**Scope:** Component interactions and end-to-end workflows

**Test Scenarios:**

| Scenario | Path | Validation |
|----------|------|------------|
| **Happy path** | Ingest → Classify → RAG → Auto-resolve | Status = auto_resolved, latency < 5s |
| **Medium confidence** | Ingest → Classify → RAG → Assign | Status = assigned, dept correct |
| **Low confidence** | Ingest → Classify → Escalate | Status = escalated, reason logged |
| **Duplicate detection** | Ingest same ticket twice | Second returns 409 Conflict |
| **PII masking** | Ingest with email/phone | PII replaced with placeholders |
| **Feedback loop** | Submit accepted feedback | KB updated, embeddings refreshed |
| **Multi-domain** | Ticket spans categories | is_multi_domain = true, escalated |
| **WebSocket** | Connect → Subscribe → Receive updates | All events received |

**Test Environment:**
- Dedicated test database with sample data
- Stubbed LLM responses for determinism
- Controlled test data (known tickets, resolutions)

---

### 3.3 Performance Testing Strategy

**Load Testing:**
- **Objective:** Verify system handles expected load
- **Method:** Gradually increase from 100 to 10,000 tickets/day
- **Metrics:** Latency (p50, p95, p99), throughput, error rate
- **Success:** All metrics within targets at 10k/day

**Stress Testing:**
- **Objective:** Find breaking point
- **Method:** Increase load until system fails
- **Metrics:** Maximum throughput before errors spike
- **Success:** Graceful degradation, no data loss

**Soak Testing:**
- **Objective:** Verify stability over time
- **Method:** Run at 80% capacity for 24 hours
- **Metrics:** Memory leaks, connection pool exhaustion
- **Success:** No degradation over time

**Spike Testing:**
- **Objective:** Handle sudden traffic bursts
- **Method:** 10x load for 5 minutes
- **Metrics:** Recovery time, error rate during spike
- **Success:** System recovers within 2 minutes

---

### 3.4 Acceptance Testing Strategy

**Criteria for Production Readiness:**

| Category | Requirement | Verification Method |
|----------|-------------|-------------------|
| **Functional** | All core features work | Manual testing checklist |
| **Performance** | Meets latency targets | Performance test report |
| **Accuracy** | Classification F1 ≥ 0.92 | Model evaluation report |
| **Reliability** | Uptime ≥ 99% over 1 week | Monitoring dashboard |
| **Security** | Passes vulnerability scan | Security audit report |
| **Usability** | Dashboard understandable | User feedback survey |

**Acceptance Test Plan:**
1. Deploy to staging environment
2. Run full test suite (unit, integration, performance)
3. Manual exploratory testing (5 hours)
4. Security scan (OWASP ZAP, Bandit)
5. Stakeholder demo and approval

---

## 4. SECURITY DESIGN

### 4.1 Authentication & Authorization Design

**Authentication Mechanism:**
- **Protocol:** OAuth 2.0 (Authorization Code Flow with PKCE)
- **Token Type:** JWT (JSON Web Tokens)
- **Token Expiry:** 1 hour (access token), 7 days (refresh token)
- **Token Storage:** HttpOnly cookies (web) or secure storage (mobile)

**JWT Structure:**
```json
{
  "header": {
    "alg": "RS256",
    "typ": "JWT"
  },
  "payload": {
    "sub": "user@company.com",
    "iss": "https://auth.company.com",
    "aud": "ticket-routing-api",
    "exp": 1234567890,
    "iat": 1234564290,
    "role": "L1 | L2 | L3 | Admin"
  },
  "signature": "..."
}
```

**Authorization Model (RBAC):**

| Role | Permissions |
|------|-------------|
| **L1** | Read own tickets, submit feedback |
| **L2** | Read all tickets, submit feedback, reassign tickets |
| **L3** | All L2 permissions, manual classification override |
| **Admin** | All permissions, system configuration, user management |

**Endpoint Authorization:**
```
POST /api/v1/tickets/ingest      → Authenticated (any role)
GET  /api/v1/tickets/{id}        → Authenticated + (own ticket OR L2+)
POST /api/v1/resolutions/feedback → Authenticated + assigned to ticket
DELETE /api/v1/tickets/{id}      → Admin only
```

---

### 4.2 Data Security Design

**Encryption At Rest:**
- Database: Full disk encryption (AES-256)
- Sensitive fields: Application-level encryption
  - PII detected during ingestion
  - User credentials
  - API keys

**Encryption In Transit:**
- TLS 1.3 for all external communications
- Certificate pinning for mobile clients
- mTLS for service-to-service communication (optional)

**PII Handling Strategy:**

| Entity Type | Detection Method | Masking Strategy |
|-------------|------------------|------------------|
| Email | Regex + NER | `[EMAIL_REDACTED]` |
| Phone | Regex | `[PHONE_REDACTED]` |
| SSN | Regex (US) | `[SSN_REDACTED]` |
| Credit Card | Luhn algorithm | `[CC_REDACTED]` |
| Name | NER (spaCy) | `[NAME_REDACTED]` |
| Address | NER | `[ADDRESS_REDACTED]` |
| IP Address | Regex | `[IP_REDACTED]` |

**Data Retention Policy:**
- Tickets: Retained indefinitely (or per compliance)
- Logs: 90 days
- Metrics: 1 year aggregated, 30 days detailed
- Backups: 30 days point-in-time recovery

---

### 4.3 Network Security Design

**Network Segmentation:**
```
┌─────────────────────────────────────────────────────────────────┐
│  Public Zone                                                     │
│  - API Gateway (TLS termination)                                 │
│  - Rate limiting, DDoS protection                                │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (Firewall)
┌─────────────────────────────────────────────────────────────────┐
│  Application Zone                                                │
│  - API servers, worker processes                                 │
│  - No direct internet access                                     │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (Firewall)
┌─────────────────────────────────────────────────────────────────┐
│  Data Zone                                                       │
│  - Database, object storage                                      │
│  - No internet access                                            │
└─────────────────────────────────────────────────────────────────┘
```

**Firewall Rules:**
- Deny all by default
- Allow HTTP/HTTPS (80/443) to API Gateway
- Allow app zone → data zone on specific ports
- Deny data zone → internet

**Rate Limiting:**
- Per-IP: 100 requests/minute
- Per-user: 1000 requests/hour
- Burst allowance: 20 requests
- Algorithm: Token bucket

---

### 4.4 Vulnerability Mitigation

**OWASP Top 10 Mitigation:**

| Vulnerability | Mitigation |
|---------------|------------|
| **Injection** | Parameterized queries, ORM, input validation |
| **Broken Auth** | OAuth 2.0, JWT, secure token storage |
| **Data Exposure** | Encryption at rest/transit, PII masking |
| **XXE** | Disable XML external entities, use JSON |
| **Access Control** | RBAC, least privilege principle |
| **Security Misconfig** | Security headers, disable debug in prod |
| **XSS** | Input sanitization, CSP headers |
| **Insecure Deserialization** | Validate before deserialize, use schemas |
| **Known Vulnerabilities** | Dependency scanning, regular updates |
| **Logging & Monitoring** | Centralized logging, alerting |

**Security Headers:**
```
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Content-Security-Policy: default-src 'self'
X-XSS-Protection: 1; mode=block
Referrer-Policy: no-referrer
```

---

## 5. PERFORMANCE REQUIREMENTS

### 5.1 Latency Targets

**End-to-End Latency Budget (5 seconds):**

| Stage | Target | Percentile |
|-------|--------|------------|
| API Gateway → Ingestion | 50ms | p95 |
| Schema validation | 10ms | p95 |
| PII detection | 150ms | p95 |
| Database write | 10ms | p95 |
| **Synchronous total** | **440ms** | **p95** |
| --- Async boundary --- |
| Embedding generation | 50ms | p95 |
| Classification | 100ms | p95 |
| RAG retrieval | 500ms | p95 |
| LLM generation | 3000ms | p95 |
| Evaluation | 1000ms | p95 |
| Routing decision | 10ms | p95 |
| **Async total** | **4660ms** | **p95** |
| **Grand total** | **5100ms** | **p95** |

**Buffer:** 400ms (7.8% margin)

---

### 5.2 Throughput Targets

**Sustained Load:**
- 10,000 tickets/day = 6.9 tickets/minute = 0.12 tickets/second
- With 5-second processing time, need capacity for 0.6 concurrent tickets
- **Design capacity:** 10x = 6 concurrent tickets (safety margin)

**Peak Load:**
- 3x sustained = 30,000 tickets/day during incidents
- **Design capacity:** Handle 18 concurrent tickets

**Batch Operations:**
- Nightly KB updates: Process 500 tickets in < 1 hour
- Model retraining: Process 10,000 tickets in < 4 hours

---

### 5.3 Resource Utilization Targets

**CPU:**
- API servers: < 70% average, < 90% peak
- Database: < 60% average, < 80% peak
- LLM inference: < 80% average (GPU)

**Memory:**
- API servers: < 75% of allocated
- Database: < 80% of allocated
- LLM model: 14GB reserved (Mistral-7B)

**Disk:**
- Database growth: < 500GB per year
- Logs: < 10GB per day
- Backups: 2x database size

**Network:**
- Internal: < 100 Mbps average
- External: < 10 Mbps average

---

## 6. MONITORING & OBSERVABILITY DESIGN

### 6.1 Metrics Strategy

**Golden Signals (SRE):**
1. **Latency:** Time to serve requests
2. **Traffic:** Number of requests per second
3. **Errors:** Rate of failed requests
4. **Saturation:** Resource utilization

**System Metrics to Track:**

| Category | Metrics | Collection Interval |
|----------|---------|-------------------|
| **API** | Request rate, latency (p50/p95/p99), error rate | 10 seconds |
| **Database** | Query time, connection pool, query rate | 10 seconds |
| **LLM** | Generation time, token/sec, GPU memory | 10 seconds |
| **Classification** | Confidence distribution, category breakdown | 1 minute |
| **RAG** | Retrieval time, relevance scores | 1 minute |
| **Business** | Auto-resolve rate, escalation rate, feedback rate | 5 minutes |

**Metric Format (Prometheus):**
```
# API latency histogram
api_request_duration_seconds{method="POST", endpoint="/tickets", status="201"}

# Throughput counter
tickets_processed_total{status="success", routing_path="auto_resolved"}

# Resource gauge
database_connections_active{pool="main"}
```

---

### 6.2 Logging Strategy

**Log Levels:**
- **ERROR:** System failures requiring immediate attention
- **WARN:** Degraded performance, fallbacks activated
- **INFO:** State changes, routing decisions
- **DEBUG:** Detailed processing (disabled in production)

**Structured Log Format:**
```json
{
  "timestamp": "2026-01-15T10:30:00.123Z",
  "level": "INFO",
  "service": "classification-service",
  "ticket_id": "TKT-12345",
  "event": "ticket_classified",
  "message": "Ticket classified with high confidence",
  "metadata": {
    "category": "Database",
    "confidence": 0.89,
    "processing_time_ms": 87
  },
  "trace_id": "uuid",
  "span_id": "uuid"
}
```

**What to Log:**
- All state transitions (with ticket_id)
- All errors (with stack trace)
- All external API calls (with latency)
- All authentication attempts
- All authorization failures

**What NOT to Log:**
- Sensitive PII (even masked)
- Passwords or tokens
- Full ticket descriptions (log IDs only)

---

### 6.3 Alerting Strategy

**Alert Severity Levels:**
- **P0 (Critical):** System down, data loss risk → Page on-call
- **P1 (High):** Degraded performance, SLO breach → Escalate after 5 min
- **P2 (Medium):** Warning signals, potential issues → Ticket created
- **P3 (Low):** Informational, trend deviation → Log only

**Alert Definitions:**

| Alert | Condition | Severity | Action |
|-------|-----------|----------|--------|
| **API Down** | No successful requests in 2 min | P0 | Page |
| **High Latency** | p95 > 8 seconds for 5 min | P1 | Escalate |
| **High Error Rate** | Error rate > 5% for 5 min | P1 | Escalate |
| **Database Slow** | Query time p95 > 100ms for 10 min | P2 | Ticket |
| **Low Auto-Resolve** | Rate < 20% for 1 hour | P2 | Ticket |
| **Disk Space** | < 10% free | P1 | Escalate |
| **Certificate Expiry** | < 30 days | P2 | Ticket |

**Alert Routing:**
- P0/P1 → PagerDuty → On-call engineer
- P2 → Jira ticket → Team queue
- P3 → Slack channel → FYI

---

### 6.4 Dashboards Design

**Dashboard 1: System Health**
- API request rate (line chart)
- API latency percentiles (line chart)
- Error rate (line chart)
- Active connections (gauge)
- Service status (green/yellow/red indicators)

**Dashboard 2: Ticket Processing**
- Tickets ingested/hour (bar chart)
- Processing latency breakdown (stacked area)
- Routing path distribution (pie chart)
- Classification confidence (histogram)

**Dashboard 3: Business KPIs**
- Auto-resolve rate (gauge, target ≥ 25%)
- Average resolution time (gauge, target < 2 hours)
- Escalation accuracy (gauge, target ≥ 90%)
- Feedback rate (gauge, target ≥ 20%)

**Dashboard 4: ML Performance**
- Classification F1 score trend (line)
- Embedding generation latency (histogram)
- RAG retrieval precision (line)
- LLM generation time (box plot)

---

## CONCLUSION

This additional documentation specifies:
- ✅ Complete API design (schemas, contracts, protocols)
- ✅ Design constraints and assumptions
- ✅ Testing strategy (unit, integration, performance, acceptance)
- ✅ Security design (auth, encryption, network, vulnerabilities)
- ✅ Performance requirements (latency, throughput, resources)
- ✅ Monitoring & observability design (metrics, logs, alerts, dashboards)

**Focus:** Design specifications and requirements, not implementation procedures.

---

**Document Prepared By:** Trail Blazers Team  
**Last Updated:** 2026  
**Status:** Complete - Ready for design review and implementation planning
