# 🎫 Ticket Investigator AI

> An AI-powered FastAPI backend service for automated customer complaint investigation in digital financial platforms.

---

## 📖 Overview

**Ticket Investigator AI** is a production-oriented backend service built with **FastAPI** that automatically investigates customer support tickets for digital financial services.

The system combines **rule-based business logic** with **Large Language Model (LLM)** reasoning to:

* Understand customer complaints
* Match relevant transactions
* Verify available evidence
* Classify complaint types
* Assess severity
* Route cases to the appropriate department
* Apply safety and review policies
* Generate structured investigation results

The goal is to provide **fast, consistent, explainable, and reliable** ticket investigations while maintaining strict business rules and safety constraints.

---

# ✨ Features

* 🤖 AI-powered complaint understanding
* 💳 Transaction matching
* 🔍 Evidence verification
* 🏷 Complaint classification
* ⚠️ Severity prediction
* 🏢 Department routing
* 🛡 Safety validation
* 👨‍💼 Human review decision
* 📝 Investigation summary generation
* 📦 Standardized JSON response
* ⚡ High-performance FastAPI backend

---

# 🛠 Technology Stack

| Technology              | Purpose                                       |
| ----------------------- | --------------------------------------------- |
| **FastAPI**             | REST API Framework                            |
| **Python**              | Backend Language                              |
| **Pydantic**            | Request & Response Validation                 |
| **OpenAI / Gemini API** | Complaint Understanding & Response Generation |
| **Rule Engine**         | Classification, Routing & Safety              |
| **Docker**              | Containerization                              |
| **Uvicorn**             | ASGI Server                                   |

---

# 📡 API Endpoints

| Method   | Endpoint                 | Description                         |
| -------- | ------------------------ | ----------------------------------- |
| **GET**  | `/api/v1/health`         | Check API health                    |
| **POST** | `/api/v1/analyze-ticket` | Analyze a customer complaint ticket |

---

# 📁 Project Structure

```text
ticket_investigator/
│
├── app/
│   ├── main.py
│   │
│   ├── api/
│   │   ├── routes.py
│   │   ├── dependencies.py
│   │   └── health.py
│   │
│   ├── schemas/
│   │   ├── request.py
│   │   ├── response.py
│   │   ├── enums.py
│   │   └── errors.py
│   │
│   ├── services/
│   │   ├── investigation_service.py
│   │   ├── complaint_service.py
│   │   ├── transaction_service.py
│   │   ├── matcher_service.py
│   │   ├── evidence_service.py
│   │   ├── classifier_service.py
│   │   ├── routing_service.py
│   │   ├── severity_service.py
│   │   ├── review_service.py
│   │   ├── safety_service.py
│   │   └── response_service.py
│   │
│   ├── ai/
│   │   ├── llm_client.py
│   │   ├── prompt_manager.py
│   │   ├── complaint_prompt.py
│   │   ├── summary_prompt.py
│   │   └── reply_prompt.py
│   │
│   ├── rules/
│   │   ├── department_rules.py
│   │   ├── severity_rules.py
│   │   ├── review_rules.py
│   │   ├── safety_rules.py
│   │   └── classification_rules.py
│   │
│   ├── utils/
│   │
│   └── config.py
│
├── tests/
├── Dockerfile
├── requirements.txt
├── .env
└── README.md
```

---

# 🏗 System Workflow

```text
Customer Complaint
        │
        ▼
Input Validation
        │
        ▼
Complaint Understanding (LLM)
        │
        ▼
Transaction Analysis
        │
        ▼
Evidence Matching
        │
        ▼
Evidence Verification
        │
        ▼
Complaint Classification
        │
        ▼
Severity Prediction
        │
        ▼
Department Routing
        │
        ▼
Safety Validation
        │
        ▼
Human Review Decision
        │
        ▼
Response Generation
        │
        ▼
Structured JSON Response
```

---

# 🧠 AI & Rule-Based Architecture

The project follows a **hybrid architecture**.

## LLM Responsibilities

The LLM is responsible for:

* Understanding customer complaints
* Extracting structured information
* Identifying complaint intent
* Generating investigation summaries
* Producing customer-friendly replies

## Rule-Based Responsibilities

Deterministic business logic is responsible for:

* Transaction matching
* Evidence verification
* Complaint classification validation
* Department routing
* Severity prediction
* Human review decision
* Safety validation
* Response schema validation

This hybrid approach combines the flexibility of AI with the reliability of deterministic business rules.

---

# 🛡 Safety Logic

The system applies multiple safety layers.

## Input Validation

* Validate required fields
* Reject malformed requests
* Enforce request schema

## Business Rule Validation

All LLM outputs are validated before returning the final response.

Examples:

* Invalid departments are rejected.
* Invalid severity values are corrected.
* Unsupported case types are blocked.

## Human Review

High-risk investigations are automatically escalated.

Examples include:

* Fraud reports
* Wrong transfers
* High-value transactions
* Conflicting evidence
* Low-confidence predictions

## Consistent Output

Every request returns a standardized JSON response, ensuring reliable downstream integration.

---

# 🔄 Investigation Pipeline

1. Receive customer complaint
2. Validate request
3. Analyze complaint using the LLM
4. Analyze transaction history
5. Match the most relevant transaction
6. Verify evidence
7. Classify the complaint
8. Predict severity
9. Route to the correct department
10. Apply safety validation
11. Decide if human review is required
12. Generate the final investigation report
13. Return the structured JSON response

---

# 🐳 Docker

## Build

```bash
docker build -t ticket-investigator .
```

## Run

```bash
docker run -p 8080:8080 ticket-investigator
```

---

# 🎯 Design Decisions

* FastAPI provides a lightweight, high-performance REST API.
* Modular service-based architecture improves maintainability.
* Rule-based validation ensures deterministic business decisions.
* LLMs are used only where natural language understanding adds value.
* Pydantic enforces strict request and response validation.
* Docker simplifies deployment across environments.

---

# ⚠ Known Limitations

* Depends on the quality of LLM responses.
* Business rules are currently static.
* No persistent database integration.
* No authentication or authorization.
* Transaction matching is limited to the provided transaction history.
* Complex fraud investigations still require manual review.
* Cloud-hosted LLM providers require internet connectivity.

---

# 🚀 Future Improvements

* Database integration
* Authentication & authorization
* Real transaction lookup service
* Advanced confidence scoring
* Enhanced multilingual support
* Fraud detection using machine learning
* Audit logging
* Monitoring dashboard
* Additional unit and integration tests
* Support for multiple LLM providers
* Retrieval-Augmented Generation (RAG) for policy-aware responses

---

# 📄 License

This project is intended for educational purposes and hackathon participation. It can be extended into a production-grade customer support investigation system with additional security, persistence, and operational features.
