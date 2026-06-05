# Open-Source Tools & Libraries - Technology Selection
## AI Powered Intelligent Ticket Routing & Resolution Agent

**Version:** 2.0 - Design Focus  
**Date:** 2026  
**Classification:** Hackathon Round 2 Documentation

---

## Executive Summary

This document specifies the technology stack for the AI-powered ticket routing system, focusing on **WHY each technology was selected** rather than how to install it. Each choice is justified against alternatives with clear design rationale.

**Selection Criteria:**
1. **Open-source:** OSI-approved licenses, no vendor lock-in
2. **Production-ready:** Battle-tested in enterprise environments
3. **Performance:** Meets our < 5 second latency target
4. **Scalability:** Supports 5,000-10,000 tickets/day growth
5. **Community:** Active development, good documentation
6. **Integration:** Works well with other chosen technologies

---

## 1. TECHNOLOGY STACK OVERVIEW

```
┌─────────────────────────────────────────────────────────────────┐
│                    PRESENTATION LAYER                            │
│  API Gateway: Kong                                               │
│  Web Framework: FastAPI                                          │
│  UI Framework: Streamlit                                         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    APPLICATION LAYER                             │
│  Multi-Agent: AutoGen                                            │
│  Workflow: Apache Airflow (batch jobs)                           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    BUSINESS LOGIC LAYER                          │
│  LLM: Mistral-7B via Ollama                                      │
│  Embeddings: sentence-transformers                               │
│  RAG: LangChain                                                  │
│  Classifier: scikit-learn                                        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    DATA LAYER                                    │
│  Database: PostgreSQL 16                                         │
│  Vector Search: pgvector extension                               │
│  Object Storage: MinIO (S3-compatible)                           │
│  Cache: Redis (optional)                                         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    INFRASTRUCTURE                                │
│  Orchestration: Kubernetes                                       │
│  Containers: Docker                                              │
│  Monitoring: Prometheus + Grafana                                │
└─────────────────────────────────────────────────────────────────┘
```

**Total Dependencies:** 40+ open-source libraries  
**Primary Language:** Python 3.11+  
**All licenses:** OSI-approved (MIT, Apache 2.0, BSD, PostgreSQL License)  
**Total infrastructure cost:** $0 (self-hosted)

---

## 2. CORE INFRASTRUCTURE TECHNOLOGIES

### 2.1 Container Orchestration: **Kubernetes**

**Why Chosen:**
- **Industry standard** for container orchestration (85% adoption in Fortune 500)
- **Native GPU support** for LLM inference (required for Mistral-7B)
- **Horizontal Pod Autoscaler** automatically scales based on CPU/memory
- **Service mesh integration** for complex networking
- **Rich ecosystem** of tools and operators

**Alternatives Considered:**

| Alternative | Pros | Cons | Rejection Reason |
|-------------|------|------|------------------|
| **Docker Swarm** | Simpler to set up | Less feature-rich, smaller ecosystem | Cannot meet scale requirements |
| **Nomad** | Good scheduler | Smaller community, less tooling | Kubernetes has better GPU support |
| **ECS** | AWS-native | Vendor lock-in, not open-source | Violates open-source requirement |

**Design Impact:**
- Enables independent scaling of API servers, LLM inference, and database
- Supports rolling updates with zero downtime
- Provides health checks and automatic restart on failure

**License:** Apache 2.0

---

### 2.2 Container Runtime: **Docker**

**Why Chosen:**
- **Standard containerization** platform (90%+ market share)
- **Excellent image ecosystem** (Docker Hub with 100k+ images)
- **Development parity** (dev environment = production)
- **Compose for multi-container** local development

**Alternatives Considered:**

| Alternative | Pros | Cons | Rejection Reason |
|-------------|------|------|------------------|
| **Podman** | Rootless, daemonless | Less ecosystem support | Docker Compose compatibility issues |
| **containerd** | Lower-level, lighter | More complex setup | Overkill for our needs |

**Design Impact:**
- Consistent deployment across dev, staging, production
- Easy local testing with Docker Compose
- Portable across cloud providers

**License:** Apache 2.0

---

## 3. API & WEB FRAMEWORKS

### 3.1 REST API Framework: **FastAPI**

**Why Chosen:**
- **Async/await native** (handles 1000+ concurrent connections per worker)
- **Automatic OpenAPI docs** generation (no manual maintenance)
- **Pydantic integration** for request/response validation
- **Best performance** among Python frameworks (comparable to Node.js)
- **Type hints** for IDE support and error prevention

**Performance Comparison:**
| Framework | Requests/sec | Latency (ms) | Async Support |
|-----------|--------------|--------------|---------------|
| FastAPI | 25,000 | 40 | Native |
| Flask | 10,000 | 100 | Via extension |
| Django REST | 5,000 | 200 | Via extension |

**Alternatives Considered:**

| Alternative | Pros | Cons | Rejection Reason |
|-------------|------|------|------------------|
| **Flask** | Simple, mature | Synchronous, slower | Cannot meet latency target |
| **Django REST** | Full-featured | Heavy, opinionated | Overkill for microservice |
| **Sanic** | Fast, async | Smaller community | FastAPI has better docs |

**Design Impact:**
- Meets < 440ms API response target
- Reduces development time with auto-validation
- Enables WebSocket support for real-time updates

**License:** MIT

---

### 3.2 API Gateway: **Kong**

**Why Chosen:**
- **Plugin ecosystem** (rate limiting, JWT, CORS built-in)
- **Declarative configuration** (YAML, version-controllable)
- **High performance** (10k+ req/sec per instance)
- **Open-source core** (enterprise features not needed)

**Alternatives Considered:**

| Alternative | Pros | Cons | Rejection Reason |
|-------------|------|------|------------------|
| **nginx** | Lightweight, fast | Less API-specific features | Would require custom Lua scripts |
| **Traefik** | Auto-discovery | Less mature plugin ecosystem | Kong more battle-tested |
| **AWS API Gateway** | Managed service | Proprietary, vendor lock-in | Violates open-source requirement |

**Design Impact:**
- Centralizes authentication, rate limiting
- Enables API versioning without code changes
- Provides built-in metrics for monitoring

**License:** Apache 2.0

---

### 3.3 UI Framework: **Streamlit**

**Why Chosen:**
- **Pure Python** (no JavaScript required)
- **Rapid prototyping** (build UI in hours, not days)
- **Real-time updates** (WebSocket under the hood)
- **Data visualization** built-in

**Alternatives Considered:**

| Alternative | Pros | Cons | Rejection Reason |
|-------------|------|------|------------------|
| **Gradio** | ML-focused | Less customizable | Streamlit more flexible |
| **Dash** | Plotly integration | More complex | Streamlit simpler for our needs |
| **React** | Full control | Requires JavaScript team | Out of scope for hackathon |

**Design Impact:**
- Enables quick demo UI for judges
- Allows monitoring dashboard without frontend developer
- Supports data-driven visualizations

**License:** Apache 2.0

---

## 4. DATABASE & STORAGE

### 4.1 Relational Database: **PostgreSQL 16**

**Why Chosen:**
- **Most advanced** open-source RDBMS (JSON, full-text search, window functions)
- **pgvector extension** (native vector search, no separate DB)
- **ACID compliance** (critical for ticket state consistency)
- **Active development** (new features every year)
- **Rich ecosystem** (ORMs, tools, monitoring)

**Feature Comparison:**
| Database | Vector Search | JSON Support | Full-Text Search | License |
|----------|---------------|--------------|------------------|---------|
| PostgreSQL | pgvector ext | Native | Native | PostgreSQL |
| MySQL | No | Limited | Basic | GPL |
| MariaDB | No | Good | Basic | GPL |
| MongoDB | Atlas Search | Native | Atlas Search | SSPL |

**Alternatives Considered:**

| Alternative | Pros | Cons | Rejection Reason |
|-------------|------|------|------------------|
| **MySQL** | Popular, familiar | Weaker JSON, no vector | Missing key features |
| **MariaDB** | MySQL-compatible | No vector support | Would need separate vector DB |
| **MongoDB** | Document model | No vector search (Atlas only) | Adds complexity, SSPL license |

**Design Impact:**
- Single database for relational + vector data (simpler architecture)
- Strong consistency for ticket routing decisions
- Advanced querying for analytics

**License:** PostgreSQL License (OSI-approved, similar to MIT)

---

### 4.2 Vector Search: **pgvector**

**Why Chosen:**
- **Native PostgreSQL** extension (no separate service)
- **IVFFlat index** (approximate nearest neighbor, O(√n) vs O(n))
- **Multiple distance metrics** (cosine, L2, inner product)
- **Production-ready** (used by Supabase, Neon)

**Performance:**
- **Query time:** ~10ms for 100k vectors, ~50ms for 1M vectors
- **Index build:** ~2 minutes for 1M vectors
- **Storage overhead:** ~20% vs raw vectors

**Alternatives Considered:**

| Alternative | Pros | Cons | Rejection Reason |
|-------------|------|------|------------------|
| **Pinecone** | Managed, fast | Proprietary, $70/mo min | Not open-source, cost |
| **Weaviate** | Feature-rich | Separate service, complex | Adds operational burden |
| **Milvus** | Highly scalable | Heavy, separate service | Overkill for our scale |
| **Qdrant** | Good performance | Separate service, newer | Adds complexity |

**Design Impact:**
- Simplifies architecture (one DB instead of two)
- Reduces latency (no network hop to vector DB)
- Lowers operational complexity (one service to manage)

**License:** PostgreSQL License

---

### 4.3 Object Storage: **MinIO**

**Why Chosen:**
- **S3-compatible API** (standard interface, easy migration)
- **Self-hosted** (data sovereignty, no egress fees)
- **High performance** (10GB/s throughput on standard hardware)
- **Multi-tenancy** support

**Use Cases in Our System:**
- Model artifacts (classifiers, embeddings)
- Exported reports
- Backup storage
- Attachment storage

**Alternatives Considered:**

| Alternative | Pros | Cons | Rejection Reason |
|-------------|------|------|------------------|
| **Ceph** | Highly distributed | Complex setup, overkill | Too heavy for our scale |
| **SeaweedFS** | Simple, fast | Smaller community | MinIO more mature |
| **AWS S3** | Managed | Proprietary, egress fees | Violates self-hosted requirement |

**Design Impact:**
- Standard S3 API means easy cloud migration later
- Self-hosted keeps costs at zero
- Enables multi-region deployment strategy

**License:** GNU AGPL v3 (acceptable for internal use)

---

## 5. MACHINE LEARNING STACK

### 5.1 Embedding Model: **sentence-transformers (all-MiniLM-L6-v2)**

**Why Chosen:**
- **Best open-source** sentence embeddings
- **384 dimensions** (good balance of quality vs speed)
- **Small size** (80MB model, loads in < 1 second)
- **Fast inference** (50ms per sentence on CPU)
- **Pre-trained** on 1B+ sentence pairs

**Model Specifications:**
| Metric | Value | Benchmark |
|--------|-------|-----------|
| Dimensions | 384 | vs 768 for larger models |
| Model size | 80 MB | vs 500MB for BERT-base |
| Inference time | 50ms CPU | vs 200ms for BERT |
| Performance | 0.82 cosine | vs 0.85 for larger models |

**Alternatives Considered:**

| Alternative | Pros | Cons | Rejection Reason |
|-------------|------|------|------------------|
| **OpenAI ada-002** | High quality (0.90) | $0.0001/1k tokens, proprietary | Ongoing costs, data privacy |
| **BERT-base** | Well-known | 768-dim, slower | Doesn't meet latency target |
| **USE (Universal Sentence Encoder)** | Google-backed | TensorFlow dependency, larger | Heavier runtime |

**Design Impact:**
- Enables < 50ms embedding generation (critical for 5s target)
- Small model fits in GPU memory alongside LLM
- Self-hosted eliminates API costs

**License:** Apache 2.0

---

### 5.2 LLM for Resolution: **Mistral-7B-Instruct**

**Why Chosen:**
- **Best 7B model** (beats Llama-2-7B on benchmarks)
- **Instruction-tuned** (follows prompts well)
- **Manageable size** (14GB, fits on consumer GPU)
- **Fast inference** (< 3s for 300 tokens on V100)
- **Permissive license** (Apache 2.0, commercial use OK)

**Performance Benchmarks:**
| Model | Parameters | Quality (MMLU) | Speed (tok/s) | License |
|-------|------------|----------------|---------------|---------|
| Mistral-7B | 7B | 60.1% | 30 | Apache 2.0 |
| Llama-2-7B | 7B | 45.3% | 28 | Llama 2 (restrictive) |
| GPT-3.5 | 175B | 70.0% | 40 | Proprietary, $0.002/1k |
| Claude-2 | ? | 75.0% | 35 | Proprietary, $0.008/1k |

**Alternatives Considered:**

| Alternative | Pros | Cons | Rejection Reason |
|-------------|------|------|------------------|
| **GPT-4 API** | Best quality | $0.03/1k tokens, latency | Cost prohibitive, data privacy |
| **Llama-2-7B** | Similar size | Lower quality, restrictive license | Mistral outperforms |
| **Phi-3-mini** | Smaller (3.8B) | Lower quality | Use as fallback only |

**Design Impact:**
- Self-hosted eliminates per-ticket costs
- Meets < 3 second generation target
- Data stays on-premises (privacy compliant)

**License:** Apache 2.0

---

### 5.3 LLM Inference Server: **Ollama**

**Why Chosen:**
- **Easy model management** (one command to download models)
- **OpenAI-compatible API** (easy integration with LangChain)
- **Automatic optimization** (quantization, batching)
- **Multi-model support** (run multiple LLMs simultaneously)

**Alternatives Considered:**

| Alternative | Pros | Cons | Rejection Reason |
|-------------|------|------|------------------|
| **vLLM** | Fastest inference | Complex setup, manual model management | Ollama easier for hackathon |
| **llama.cpp** | Lightest weight | Low-level, manual optimization | Too hands-on |
| **HuggingFace TGI** | Production-ready | Docker-only, heavier | Ollama simpler |

**Design Impact:**
- Reduces setup complexity (critical for demo)
- Enables quick model swapping for experiments
- Standard API simplifies testing

**License:** MIT

---

### 5.4 RAG Framework: **LangChain**

**Why Chosen:**
- **Comprehensive RAG tools** (retrievers, chains, prompts)
- **Modular design** (swap components easily)
- **Large ecosystem** (100+ integrations)
- **Active development** (weekly releases)

**Alternatives Considered:**

| Alternative | Pros | Cons | Rejection Reason |
|-------------|------|------|------------------|
| **LlamaIndex** | RAG-focused | Less flexible than LangChain | LangChain more general |
| **Haystack** | Production-ready | More opinionated | LangChain more flexible |
| **Custom** | Full control | Reinventing wheel | LangChain proven |

**Design Impact:**
- Accelerates RAG pipeline development
- Provides pre-built retriever abstractions
- Enables easy LLM swapping

**License:** MIT

---

### 5.5 Traditional ML: **scikit-learn**

**Why Chosen:**
- **Fast training** (seconds for 1k samples)
- **Interpretable models** (Logistic Regression coefficients visible)
- **Sufficient accuracy** (92%+ F1 for text classification)
- **CPU-only** (no GPU required for inference)
- **Mature, stable** (20+ years of development)

**Alternatives Considered:**

| Alternative | Pros | Cons | Rejection Reason |
|-------------|------|------|------------------|
| **XGBoost** | Higher accuracy (95%+) | Slower, less interpretable | Marginal gain not worth complexity |
| **Neural Network** | Highest accuracy | GPU needed, slower training | Overkill for our task |
| **LightGBM** | Fast, accurate | Similar to XGBoost | scikit-learn simpler |

**Design Impact:**
- Enables < 100ms classification (on CPU)
- Model retraining takes minutes, not hours
- Coefficients help debug misclassifications

**License:** BSD-3-Clause

---

### 5.6 Multi-Agent Framework: **AutoGen**

**Why Chosen:**
- **Built for LLM agents** (not adapted from chatbots)
- **GroupChat pattern** (natural for multi-agent workflow)
- **Human-in-the-loop** (UserProxy for confirmations)
- **Conversation state** managed automatically
- **Microsoft-backed** (active development, good docs)

**Alternatives Considered:**

| Alternative | Pros | Cons | Rejection Reason |
|-------------|------|------|------------------|
| **CrewAI** | Simple API | Less flexible than AutoGen | Cannot customize workflow |
| **LangGraph** | State machine control | More complex, newer | Steeper learning curve |
| **Custom** | Full control | Complex state management | AutoGen handles this |

**Design Impact:**
- Simplifies multi-agent coordination
- Provides built-in message routing
- Enables human confirmation for auto-resolve path

**License:** Apache 2.0

---

## 6. DATA PROCESSING & VALIDATION

### 6.1 Schema Validation: **Pydantic**

**Why Chosen:**
- **Type safety** at runtime
- **FastAPI integration** (native support)
- **Clear error messages** (tells user exactly what's wrong)
- **Performance** (compiled with Rust core)

**Design Impact:**
- Prevents invalid data from entering system
- Reduces debugging time (errors caught early)
- Self-documenting API (schemas in code)

**License:** MIT

---

### 6.2 PII Detection: **Presidio**

**Why Chosen:**
- **Pre-trained** on 50+ entity types
- **Customizable** (add domain-specific patterns)
- **Microsoft-backed** (used in Azure)
- **Multi-language** support

**Alternatives Considered:**

| Alternative | Pros | Cons | Rejection Reason |
|-------------|------|------|------------------|
| **spaCy NER** | General NER | Not specialized for PII | Presidio better for privacy |
| **AWS Comprehend** | Managed | Proprietary, $0.0001/unit | Not open-source |

**Design Impact:**
- Ensures GDPR/DPDP compliance
- Protects sensitive data automatically
- Enables safe data sharing for training

**License:** MIT

---

## 7. MONITORING & OBSERVABILITY

### 7.1 Metrics: **Prometheus**

**Why Chosen:**
- **Industry standard** for metrics (CNCF graduated)
- **Pull-based** (no agent installation)
- **Powerful query language** (PromQL)
- **Alerting** built-in

**Design Impact:**
- Enables SLO tracking (latency, error rate)
- Provides data for auto-scaling decisions
- Integrates with Grafana for visualization

**License:** Apache 2.0

---

### 7.2 Visualization: **Grafana**

**Why Chosen:**
- **Best-in-class** dashboarding
- **Prometheus integration** (native)
- **Alerting** built-in
- **Template dashboards** for common scenarios

**Design Impact:**
- Provides real-time system visibility
- Enables proactive issue detection
- Supports business metrics (auto-resolve rate, etc.)

**License:** AGPL v3 (acceptable for internal use)

---

## 8. LICENSE COMPATIBILITY

### 8.1 License Summary

| License Type | Libraries | Commercial Use | Modification | Distribution |
|--------------|-----------|----------------|--------------|--------------|
| **MIT** | FastAPI, Pydantic, LangChain, Presidio, Ollama | ✅ | ✅ | ✅ |
| **Apache 2.0** | Kubernetes, Kong, Mistral-7B, AutoGen, sentence-transformers, Prometheus | ✅ | ✅ | ✅ |
| **BSD-3-Clause** | scikit-learn, pandas, NumPy | ✅ | ✅ | ✅ |
| **PostgreSQL** | PostgreSQL, pgvector | ✅ | ✅ | ✅ |
| **AGPL v3** | MinIO, Grafana | ⚠️ Copyleft* | ✅ | ⚠️ |

*AGPL requires sharing modifications if deployed as a service. Acceptable for internal use and hackathon demo. For SaaS product, consider alternatives.

**All licenses are OSI-approved open-source.**

---

## 9. DESIGN DECISION SUMMARY

### 9.1 Key Technology Choices

| Component | Chosen | Primary Reason |
|-----------|--------|----------------|
| **Database** | PostgreSQL + pgvector | Unified DB for relational + vector data |
| **LLM** | Mistral-7B via Ollama | Best open-source 7B model, self-hosted |
| **Embeddings** | all-MiniLM-L6-v2 | Optimal speed/quality trade-off |
| **API** | FastAPI | Async support, automatic docs, fast |
| **Classifier** | Logistic Regression | Fast, interpretable, sufficient accuracy |
| **RAG** | LangChain + Hybrid retrieval | Comprehensive tooling, flexible |
| **Agents** | AutoGen | Built for LLM agents, GroupChat pattern |
| **Gateway** | Kong | Plugin ecosystem, declarative config |

### 9.2 Design Principles Applied

1. **Simplicity:** Prefer fewer moving parts (PostgreSQL + pgvector vs separate vector DB)
2. **Performance:** All choices meet < 5 second latency target
3. **Cost:** Zero ongoing costs (all self-hosted)
4. **Flexibility:** Easy to swap components (LLM, embeddings, retriever)
5. **Observability:** Built-in metrics and monitoring
6. **Maintainability:** Mature, well-documented technologies

---

## 10. DEPENDENCY MATRIX

### 10.1 Core Dependencies

| Layer | Component | Version | License | Alternatives Considered |
|-------|-----------|---------|---------|------------------------|
| **API** | FastAPI | 0.104+ | MIT | Flask, Django REST |
| **Database** | PostgreSQL | 16+ | PostgreSQL | MySQL, MongoDB |
| **Vector** | pgvector | 0.5+ | PostgreSQL | Pinecone, Weaviate |
| **Embeddings** | sentence-transformers | 2.2+ | Apache 2.0 | OpenAI ada-002 |
| **LLM** | Mistral-7B | 7B | Apache 2.0 | GPT-4, Llama-2 |
| **LLM Server** | Ollama | 0.1.17+ | MIT | vLLM, llama.cpp |
| **RAG** | LangChain | 0.0.335+ | MIT | LlamaIndex, Haystack |
| **Agents** | AutoGen | 0.2+ | Apache 2.0 | CrewAI, LangGraph |
| **Classifier** | scikit-learn | 1.3+ | BSD-3 | XGBoost, Neural Net |
| **Gateway** | Kong | 3.4+ | Apache 2.0 | nginx, Traefik |
| **Monitoring** | Prometheus | 2.47+ | Apache 2.0 | Datadog, New Relic |

**Total: 40+ libraries, all open-source, zero licensing costs**

---

## CONCLUSION

This technology stack is designed for:
- ✅ **Zero cost:** All open-source, self-hosted
- ✅ **High performance:** Meets all latency targets
- ✅ **Scalability:** Supports 10,000+ tickets/day
- ✅ **Simplicity:** Minimal moving parts
- ✅ **Flexibility:** Easy component swapping
- ✅ **Production-ready:** Battle-tested technologies

**Every technology choice is justified with clear rationale and alternatives considered.**

---

**Document Prepared By:** Trail Blazers Team  
**Last Updated:** 2026  
**Focus:** Design decisions, not implementation instructions
