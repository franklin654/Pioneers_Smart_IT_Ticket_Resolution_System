# List of Data Sources - Design Specification

## AI Powered Intelligent Ticket Routing & Resolution Agent

**Version:** 2.0 - Design Focus  
**Date:** 2026  
**Classification:** Hackathon Round 2 Documentation

---

## Executive Summary

This document specifies all data sources required for the AI-powered ticket routing system, focusing on **data requirements, schemas, and integration specifications** rather than implementation code. The system is designed around synthetic datasets and open-source Kaggle datasets for the hackathon, with architecture supporting seamless migration to production ITSM data sources.

---

## 1. DATA SOURCE REQUIREMENTS

### 1.1 Classifier Training Data Requirements

**Purpose:** Train supervised classifier to predict ticket category

**Requirements:**

- **Minimum volume:** 1,000 labeled tickets
- **Recommended volume:** 5,000+ for production-grade accuracy
- **Category distribution:** Balanced across 6 categories (or 24 subcategories)
- **Label quality:** Human-verified or LLM-generated with validation
- **Text quality:** Realistic technical language, 50-5000 characters
- **Split ratio:** 80% training / 20% testing

**Why These Requirements:**

- 1,000 tickets → F1-score ~0.85-0.90
- 5,000 tickets → F1-score ~0.92-0.95 (target ≥ 0.92)
- Balanced distribution prevents category bias
- Realistic language ensures model generalizes to production

---

### 1.2 RAG Knowledge Base Data Requirements

**Purpose:** Populate vector database for similarity search and resolution generation

**Requirements:**

- **Minimum volume:** 1,000 ticket-resolution pairs
- **Recommended volume:** 10,000+ for comprehensive coverage
- **Resolution quality:** Actionable steps (3-5 steps), not vague
- **Resolution completeness:** Includes verification steps
- **Ticket diversity:** Cover common and edge cases
- **Resolution source:** Human-written or validated AI-generated

**Why These Requirements:**

- 1,000 pairs → Covers common issues (70-80% auto-resolve)
- 10,000 pairs → Covers edge cases (85-90% auto-resolve)
- Actionable resolutions enable L1 agents to execute
- Diversity ensures retrieval finds relevant matches

---

### 1.3 Evaluation Data Requirements

**Purpose:** Measure system accuracy and performance

**Requirements:**

- **Test set size:** 20% of training data (held-out)
- **End-to-end test cases:** 200 new tickets (not in training)
- **Edge case coverage:** 50 manually crafted ambiguous tickets
- **Ground truth labels:** Human-verified categories
- **Resolution quality labels:** Human ratings (1-5 scale)

---

## 2. PRIMARY DATA SOURCES (Hackathon)

### 2.1 Synthetic Training Dataset

**Description:** AI-generated realistic IT support tickets covering all categories

**Specifications:**

| Attribute | Value |
|-----------|-------|
| **Source Type** | LLM-generated (Mistral-7B or GPT-4) |
| **Volume** | 1,000 tickets |
| **Category Distribution** | Balanced: ~167 per category |
| **Format** | CSV |
| **Generation Method** | Prompt-based with template |
| **Quality Assurance** | Manual review of 10% sample |

**Data Schema:**

```
Required Fields:
  ticket_id: string, unique, format: [A-Z]+-\d{4}
  title: string, length: 10-200 chars
  description: string, length: 50-5000 chars
  category: enum [Infrastructure, Application, Security, Database, Access Management, Network]
  subcategory: string, domain-specific
  priority: enum [Low, Medium, High, Critical]
  resolution: string, 3-5 numbered steps
  created_at: ISO 8601 timestamp
  resolved_at: ISO 8601 timestamp

Optional Fields:
  source: string (servicenow, jira, manual)
  source_id: string (external ID)
  affected_users: integer
  sla_target_hours: integer
```

**Category Distribution Design:**

| Category | Count | Example Subcategories |
|----------|-------|----------------------|
| Infrastructure | 167 | Server, VM, Container, Hardware |
| Application | 167 | Web App, API, Mobile, Desktop |
| Security | 167 | Access Control, Vulnerability, Compliance |
| Database | 166 | Performance, Backup, Replication |
| Access Management | 166 | Authentication, Authorization, SSO, MFA |
| Network | 167 | Connectivity, VPN, DNS, Firewall |

**Quality Requirements:**

- No duplicate titles (> 95% uniqueness)
- All tickets have complete resolutions
- Realistic technical details (error codes, IP addresses, logs)
- Varied priority: 30% Low, 40% Medium, 20% High, 10% Critical
- Resolution steps are actionable and specific

**Use Cases:**

1. **Classifier Training:** 800 tickets (80% split)
2. **Classifier Testing:** 200 tickets (20% split)
3. **RAG Knowledge Base:** All 1,000 tickets with resolutions
4. **Embedding Generation:** Generate 384-dim vectors for all

---

### 2.2 Kaggle: IT Support Ticket Classification Dataset

**Description:** Public dataset of real-world IT support tickets

**Specifications:**

| Attribute | Value |
|-----------|-------|
| **Source** | <https://www.kaggle.com/datasets/suraj520/it-support-ticket-classification> |
| **Volume** | ~5,000 tickets |
| **Original Categories** | Hardware, Software, Network, Access, Email |
| **Format** | CSV |
| **Quality** | Community-vetted, realistic tickets |

**Category Mapping Required:**

| Kaggle Category | Our Category | Rationale |
|----------------|--------------|-----------|
| Hardware | Infrastructure | Physical/server issues |
| Software | Application | App-level issues |
| Network | Network | Direct mapping |
| Access | Access Management | Authentication/authorization |
| Email | Application | Application service |
| Database | Database | If present |

**Expected After Preprocessing:** ~4,000 usable tickets

- Filter: Remove tickets with missing descriptions
- Filter: Remove tickets < 50 characters
- Filter: Remove exact duplicates
- Validation: Verify category mapping makes sense

**Use Cases:**

1. **Classifier Training:** 3,200 tickets (augmentation)
2. **Classifier Testing:** 800 tickets (additional test set)
3. **Total Training Data:** 800 (synthetic) + 3,200 (Kaggle) = 4,000 tickets

**Design Decision:** Augment synthetic data with real-world language patterns

---

### 2.3 Kaggle: Customer Support Ticket Dataset

**Description:** Larger dataset with resolved tickets and resolutions

**Specifications:**

| Attribute | Value |
|-----------|-------|
| **Source** | <https://www.kaggle.com/datasets/suraj520/customer-support-ticket-dataset> |
| **Volume** | ~10,000 tickets |
| **Format** | JSON |
| **Key Advantage** | Contains resolution text |

**Schema (Relevant Fields):**

```json
{
  "ticket_id": "string",
  "subject": "string (ticket title)",
  "description": "string (ticket details)",
  "category": "string (needs mapping)",
  "priority": "string",
  "status": "string (Resolved, Open, Closed)",
  "resolution": "string (resolution steps)",
  "created_date": "ISO 8601",
  "resolved_date": "ISO 8601"
}
```

**Filtering Criteria:**

| Filter | Condition | Rationale |
|--------|-----------|-----------|
| Status | = 'Resolved' | Only resolved tickets for RAG |
| Resolution | Not null, length ≥ 30 chars | Must have actionable resolution |
| Description | Length ≥ 50 chars | Sufficient context for classification |
| Category | In technical domains | Filter out non-IT categories |

**Expected After Filtering:** ~8,000 usable tickets

**Use Cases:**

1. **Classifier Training:** 6,400 tickets (80%)
2. **Classifier Testing:** 1,600 tickets (20%)
3. **RAG Knowledge Base:** All 8,000 resolved tickets
4. **Total Training Data:** 4,000 + 6,400 = 10,400 tickets
5. **Total RAG KB:** 1,000 (synthetic) + 8,000 (Kaggle) = 9,000 ticket-resolution pairs

**Design Decision:** Primary source for RAG knowledge base due to resolution quality

---

### 2.4 StackOverflow Questions Dataset

**Description:** Technical Q&A converted to ticket-resolution format

**Specifications:**

| Attribute | Value |
|-----------|-------|
| **Source** | <https://www.kaggle.com/datasets/stackoverflow/stackoverflow> |
| **Volume** | Sample 50,000 questions |
| **Format** | XML → CSV conversion |
| **Filtering** | By tags matching our categories |

**Tag-to-Category Mapping:**

| Tags | Our Category | Example Tags |
|------|--------------|--------------|
| `database, sql, postgresql, mysql` | Database | Performance, queries, indexing |
| `networking, tcp, dns, vpn` | Network | Connectivity, protocols |
| `server, linux, docker, kubernetes` | Infrastructure | Deployment, configuration |
| `security, authentication, ssl` | Security | Encryption, vulnerabilities |
| `oauth, ldap, permissions, rbac` | Access Management | Auth, authz, identity |

**Filtering Criteria:**

- Questions with accepted answers only (quality indicator)
- Score ≥ 5 (community validation)
- Tags match our 6 categories
- Answer length ≥ 100 characters (sufficient detail)

**Conversion to Ticket Format:**

```
Question Title → Ticket Title
Question Body → Ticket Description
Top-Voted Answer → Resolution Steps
Tags → Category/Subcategory
```

**Expected After Processing:** ~50,000 ticket-resolution pairs

**Use Cases:**

1. **RAG Knowledge Base Only:** Not for classifier training (different domain)
2. **Total RAG KB:** 9,000 + 50,000 = 59,000 entries
3. **Benefit:** Deep technical knowledge for complex issues

**Design Decision:** StackOverflow provides technical depth that synthetic/CSV data lacks

---

## 3. PRODUCTION DATA SOURCES (Post-Hackathon)

### 3.1 ITSM Integration Specification

**Purpose:** Real-time ticket ingestion from enterprise ITSM platforms

**Supported Systems:**

- ServiceNow (webhook)
- Jira Service Management (webhook)
- Zendesk (API polling)
- Freshdesk (webhook)

**Integration Architecture:**

```
ITSM System → Webhook/API → API Gateway → Ingestion Service → Database
```

**Requirements:**

- **Authentication:** OAuth 2.0 or API tokens
- **Rate Limiting:** 100 requests/minute
- **Payload Format:** JSON
- **Delivery Guarantee:** At-least-once (idempotent ingestion)
- **Retry Strategy:** Exponential backoff (1s, 2s, 4s, 8s, 16s)

---

### 3.2 ServiceNow Webhook Specification

**Trigger:** When incident is created or updated

**Payload Schema:**

```json
{
  "sys_id": "string (ServiceNow internal ID)",
  "number": "string (INC0012345)",
  "short_description": "string (ticket title)",
  "description": "string (detailed description)",
  "category": "string (ServiceNow category)",
  "subcategory": "string",
  "priority": "string (1-Critical, 2-High, 3-Medium, 4-Low)",
  "state": "string (New, In Progress, Resolved)",
  "assignment_group": "string (team name)",
  "opened_at": "ISO 8601 timestamp",
  "sys_created_by": "string (user email)",
  "sys_updated_on": "ISO 8601 timestamp"
}
```

**Mapping to Our Schema:**

| ServiceNow Field | Our Field | Transformation |
|------------------|-----------|----------------|
| number | ticket_id | Direct mapping |
| short_description | title | Direct mapping |
| description | description | Direct mapping |
| category | category | Requires mapping table |
| priority | priority | Map 1→Critical, 2→High, 3→Medium, 4→Low |
| state | status | Map New→new, In Progress→in_progress |
| opened_at | created_at | Direct mapping |

**Category Mapping Design:**

ServiceNow uses different category names, requires mapping table:

```
ServiceNow "Hardware" → Our "Infrastructure"
ServiceNow "Software" → Our "Application"
ServiceNow "Inquiry" → Filter out (not incident)
```

---

### 3.3 Jira Service Management Webhook Specification

**Trigger:** When issue is created (type = Incident or Service Request)

**Payload Schema:**

```json
{
  "webhookEvent": "jira:issue_created",
  "issue": {
    "id": "string",
    "key": "string (SUPPORT-5678)",
    "fields": {
      "summary": "string (title)",
      "description": "string (details)",
      "issuetype": {"name": "Incident"},
      "priority": {"name": "High"},
      "status": {"name": "Open"},
      "created": "ISO 8601",
      "updated": "ISO 8601",
      "reporter": {"emailAddress": "string"}
    }
  }
}
```

**Mapping to Our Schema:**

| Jira Field | Our Field | Transformation |
|------------|-----------|----------------|
| issue.key | ticket_id | Direct mapping |
| fields.summary | title | Direct mapping |
| fields.description | description | Direct mapping |
| fields.priority.name | priority | Direct mapping |
| fields.status.name | status | Map Open→new, In Progress→in_progress |

---

## 4. SECONDARY DATA SOURCES (System Observability)

### 4.1 Monitoring Metrics

**Purpose:** Track system performance and ML model drift

**Data Sources:**

- Prometheus metrics (API latency, throughput, error rate)
- Application logs (ticket processing events)
- Database query logs (slow queries, connection pool)

**Metrics to Track:**

| Metric Category | Examples | Use Case |
|----------------|----------|----------|
| **Performance** | API latency, throughput | Detect bottlenecks |
| **ML Quality** | Classification confidence distribution | Detect model drift |
| **Business** | Auto-resolve rate, escalation rate | Measure effectiveness |

**Storage:** Time-series database (Prometheus)

---

### 4.2 Authentication & Access Logs

**Purpose:** Security audit trail and user behavior analysis

**Data Sources:**

- OAuth provider logs (login attempts, token refresh)
- API gateway logs (endpoint access, rate limiting)
- Database audit logs (data access, modifications)

**Use Cases:**

- Security incident investigation
- User activity analysis
- Compliance reporting

**Storage:** Structured logs (JSON format)

---

### 4.3 PII Detection Results

**Purpose:** Track PII masking effectiveness

**Data Format:**

```json
{
  "ticket_id": "string",
  "entities_detected": [
    {
      "entity_type": "EMAIL_ADDRESS | PHONE | SSN | CREDIT_CARD | NAME | ADDRESS | IP",
      "start": "integer (character position)",
      "end": "integer",
      "confidence": "float [0.0-1.0]",
      "masked_value": "string ([EMAIL_REDACTED])"
    }
  ],
  "detection_timestamp": "ISO 8601"
}
```

**Storage:** PostgreSQL `pii_detections` table

**Use Cases:**

- PII detection accuracy measurement
- Compliance audit trail
- Model improvement (false positives/negatives)

---

### 4.4 Model Training Artifacts

**Purpose:** Track model versions and training runs

**Data Sources:**

- Model checkpoints (classifier weights)
- Training metrics (loss, accuracy, F1)
- Hyperparameters (learning rate, batch size)
- Evaluation results (confusion matrix, per-category F1)

**Storage:** MLflow tracking server + MinIO object storage

**Metadata Schema:**

```json
{
  "run_id": "string (UUID)",
  "model_type": "classifier | embedding | llm",
  "version": "string (v1.0, v1.1)",
  "training_data": {
    "source": "synthetic + kaggle",
    "size": 10400,
    "distribution": {"Infrastructure": 1733, "Application": 1734, ...}
  },
  "hyperparameters": {
    "learning_rate": 2e-5,
    "batch_size": 32,
    "epochs": 10
  },
  "metrics": {
    "f1_score": 0.923,
    "precision": 0.918,
    "recall": 0.927
  },
  "artifacts": {
    "model_path": "s3://models/classifier_v1.pkl",
    "confusion_matrix": "s3://artifacts/confusion_v1.png"
  }
}
```

---

## 5. DATA INTEGRATION ARCHITECTURE

### 5.1 Integration Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                    EXTERNAL SOURCES                              │
│  Synthetic CSV | Kaggle CSV/JSON | ITSM Webhooks | StackOverflow│
└─────────────────────────┬───────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│                    INGESTION LAYER                               │
│  Schema Validation | PII Detection | Deduplication | Mapping    │
└─────────────────────────┬───────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│                    PERSISTENCE LAYER                             │
│  PostgreSQL (tickets) | pgvector (embeddings) | MinIO (artifacts)│
└─────────────────────────┬───────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│                    PROCESSING LAYER                              │
│  Classification | RAG Retrieval | LLM Generation | Evaluation   │
└─────────────────────────────────────────────────────────────────┘
```

---

### 5.2 Data Flow Design

**Ingestion Flow:**

1. **Receive:** Accept ticket from source (webhook, CSV, API)
2. **Validate:** Check schema compliance
3. **Mask PII:** Detect and replace sensitive data
4. **Deduplicate:** Check for existing ticket
5. **Persist:** Store in PostgreSQL
6. **Trigger:** Queue for embedding/classification

**Training Data Preparation Flow:**

1. **Collect:** Load synthetic + Kaggle datasets
2. **Clean:** Remove duplicates, invalid entries
3. **Balance:** Ensure category distribution
4. **Split:** 80/20 train/test
5. **Generate Embeddings:** Create 384-dim vectors
6. **Store:** Save to training dataset format

**RAG Knowledge Base Build Flow:**

1. **Filter:** Select only resolved tickets
2. **Validate:** Ensure resolution quality
3. **Generate Embeddings:** Create vectors
4. **Index:** Store in pgvector with IVFFlat index
5. **Test:** Verify retrieval accuracy

---

## 6. DATA QUALITY SPECIFICATIONS

### 6.1 Validation Rules

**Ingestion-Time Validation:**

| Field | Rule | Action on Failure |
|-------|------|-------------------|
| ticket_id | Unique, format [A-Z]+-\d+ | Reject with 400 error |
| title | 10-200 chars | Reject with 400 error |
| description | 50-5000 chars | Reject with 400 error |
| category | Valid enum (if provided) | Accept, classify later |
| priority | Valid enum | Reject with 400 error |
| created_at | Valid ISO 8601 | Reject with 400 error |

**Post-Ingestion Validation:**

| Check | Threshold | Action |
|-------|-----------|--------|
| PII detection | Any entity found | Mask and log |
| Duplicate detection | Similarity > 0.95 | Flag for review |
| Language detection | Not English | Flag for manual routing |

---

### 6.2 Data Quality Metrics

**Track Over Time:**

| Metric | Target | Measurement |
|--------|--------|-------------|
| Schema compliance rate | > 99% | % of valid ingestions |
| PII masking coverage | 100% | % of PII successfully masked |
| Duplicate rate | < 5% | % of tickets flagged as duplicate |
| Category distribution | Balanced | Max deviation < 20% from mean |

---

## 7. DATA AVAILABILITY MATRIX

| Data Source | Hackathon | Production | Volume | Update Frequency |
|-------------|-----------|------------|--------|------------------|
| **Synthetic Dataset** | ✅ Available | ❌ Not applicable | 1,000 | One-time |
| **Kaggle IT Support** | ✅ Available | ❌ Static | 5,000 | Static |
| **Kaggle Customer Support** | ✅ Available | ❌ Static | 10,000 | Static |
| **StackOverflow** | ✅ Available | ❌ Static | 50,000 | Static |
| **ServiceNow Webhook** | ❌ Not available | ✅ Production | 5,000/day | Real-time |
| **Jira Webhook** | ❌ Not available | ✅ Production | 3,000/day | Real-time |
| **Pre-trained Models** | ✅ Available | ✅ Available | Static | Manual update |
| **Monitoring Metrics** | ✅ Generated | ✅ Generated | Continuous | 15-sec intervals |

---

## 8. DATA SOURCE DESIGN DECISIONS

### 8.1 Why Synthetic + Kaggle (Hackathon)?

**Decision:** Use combination of synthetic and public datasets

**Rationale:**

- Real production data unavailable for hackathon
- Synthetic ensures coverage of all categories
- Kaggle provides realistic language patterns
- Combination achieves sufficient volume (10k+ tickets)
- Cost: $0 (vs labeled data procurement)

**Trade-offs:**

- ✅ Pro: Complete control over distribution
- ✅ Pro: No data privacy concerns
- ✅ Pro: Immediate availability
- ⚠️ Con: May not capture all production edge cases
- ⚠️ Con: Requires validation on real data eventually

---

### 8.2 Why StackOverflow for RAG?

**Decision:** Include StackOverflow Q&A in knowledge base

**Rationale:**

- Deep technical content (code examples, error explanations)
- Community-validated answers (accepted + high score)
- Covers edge cases not in typical support tickets
- Augments synthetic resolutions

**Trade-offs:**

- ✅ Pro: Free, high-quality technical content
- ✅ Pro: 50k+ examples for comprehensive coverage
- ⚠️ Con: Different writing style than corporate support
- ⚠️ Con: Requires Q&A → ticket-resolution conversion

---

### 8.3 Why Not Use All Kaggle Data?

**Decision:** Filter Kaggle datasets heavily (5k → 4k, 10k → 8k)

**Rationale:**

- Quality over quantity for training data
- Remove tickets without sufficient detail
- Remove tickets without resolutions (for RAG)
- Ensure clean test set

**Trade-offs:**

- ✅ Pro: Higher quality training data
- ✅ Pro: Better model accuracy
- ⚠️ Con: Reduced volume
- ⚠️ Con: May remove some edge cases

---

## 9. DATASET USAGE SUMMARY

### Classifier Training

- **Synthetic:** 800 tickets (primary, balanced)
- **Kaggle IT Support:** 3,200 tickets (augmentation)
- **Kaggle Customer Support:** 6,400 tickets (augmentation)
- **Total:** 10,400 training tickets
- **Target F1:** ≥ 0.92

### Classifier Testing

- **Synthetic:** 200 tickets (held-out)
- **Kaggle IT Support:** 800 tickets (held-out)
- **Kaggle Customer Support:** 1,600 tickets (held-out)
- **Total:** 2,600 test tickets

### RAG Knowledge Base

- **Synthetic:** 1,000 ticket-resolution pairs
- **Kaggle Customer Support:** 8,000 pairs
- **StackOverflow:** 50,000 Q&A pairs
- **Total:** 59,000 knowledge base entries
- **Target Retrieval Precision@5:** ≥ 0.80

### End-to-End Testing

- **New Synthetic:** 200 tickets (separate generation)
- **Manual Edge Cases:** 50 tickets (ambiguous, multi-domain)
- **Target:** < 5s latency, ≥ 90% correct routing

---

## CONCLUSION

This data source specification provides:

- ✅ Complete data requirements for all system components
- ✅ Clear schema specifications for each source
- ✅ Integration architecture for production sources
- ✅ Quality validation rules
- ✅ Design decisions with rationale

**No implementation code** - pure data design specifications ready for data engineering team.

---

**Document Prepared By:** Trail Blazers Team  
**Last Updated:** 2026  
**Status:** Design-focused, implementation-independent
