AutoCloud AI

AI-Powered Cloud Infrastructure Monitoring and Resource Optimisation

Project Type: MSc Artificial Intelligence / Cloud AI Engineering
Cloud Platform: Google Cloud Platform (GCP)
Primary Language: Python
Development Approach: Modular, scalable, cloud-native architecture

---

1. Project Overview

AutoCloud AI is an intelligent cloud infrastructure monitoring and resource optimisation platform that uses Machine Learning and AI agents to monitor cloud infrastructure, identify inefficient resource utilisation, predict future resource requirements, detect anomalies and recommend infrastructure optimisation strategies.

The system will initially operate in recommendation mode with human approval for infrastructure changes. Autonomous execution of approved scaling actions can be introduced in later development phases.

The primary objective is to reduce unnecessary cloud expenditure while maintaining application performance, availability and reliability.

1.1 Core Problems

Traditional cloud infrastructure management involves several challenges:

- Underutilised cloud resources.
- Unexpected increases in infrastructure costs.
- CPU and memory resource wastage.
- Unpredictable application traffic.
- Inefficient manual scaling decisions.
- Lack of intelligent resource prediction.
- Difficulty identifying abnormal infrastructure behaviour.

AutoCloud AI aims to address these problems using predictive analytics, anomaly detection and intelligent optimisation recommendations.

2. Project Objectives

The system must:

1. Collect infrastructure metrics from Google Cloud Platform.
2. Monitor CPU, memory, network traffic and application requests.
3. Identify abnormal resource utilisation.
4. Predict future resource requirements.
5. Estimate infrastructure expenditure.
6. Generate intelligent optimisation recommendations.
7. Explain recommendations using an LLM-powered AI agent.
8. Provide an interactive monitoring dashboard.
9. Support human-approved infrastructure scaling.
10. Evaluate cost savings and infrastructure performance improvements.

3. Technology Stack

Use the following technologies.

Component| Technology
Programming Language| Python 3.11+
Cloud Platform| Google Cloud Platform
Application Deployment| Cloud Run
Containerisation| Docker
Container Registry| Artifact Registry
Infrastructure Monitoring| Cloud Monitoring
Data Storage| BigQuery
Object Storage| Cloud Storage
Messaging| Pub/Sub
Machine Learning| Scikit-learn
Anomaly Detection| Isolation Forest
Resource Prediction| XGBoost
Deep Learning (optional)| LSTM
AI Agent| LangGraph
LLM| Gemini through Vertex AI
Dashboard| Streamlit
API Development| FastAPI
CI/CD| Cloud Build
Version Control| Git and GitHub

Prefer managed GCP services to minimise infrastructure administration.

Do not introduce Kubernetes unless a specific project requirement justifies it.

4. System Architecture

Implement the following architecture:

                GCP Infrastructure
                        |
                        v
                 Cloud Monitoring
                        |
                        v
                Metrics Collection
                        |
                        v
                 Data Processing
                        |
                  +-----+-----+
                  |           |
                  v           v
               BigQuery   Cloud Storage
                  |
                  v
             AI Analytics Engine
                  |
          +-------+--------+
          |       |        |
          v       v        v
       Anomaly  Resource   Cost
       Detection Prediction Analysis
          |       |        |
          +-------+--------+
                  |
                  v
            Optimisation Agent
                  |
                  v
           Recommendation Engine
                  |
                  v
              FastAPI
                  |
                  v
          Streamlit Dashboard
                  |
                  v
           Human Approval Layer
                  |
                  v
          GCP Scaling Operations

5. Major System Modules

Module 1: Cloud Infrastructure Monitoring

Purpose: Collect real-time or periodically sampled infrastructure metrics.

Monitor:

- CPU utilisation.
- Memory utilisation where available.
- Network ingress and egress.
- Application request count.
- Request latency.
- Container instance count.
- Application error rate.

Implementation:

- Use Google Cloud Monitoring APIs.
- Retrieve metrics through Python.
- Store processed metrics in BigQuery.
- Maintain timestamps for historical analysis.

Important: Cloud Run does not expose every infrastructure metric by default. Use supported metrics and application-level instrumentation for additional measurements.

Module 2: Data Collection and Processing

Develop a reusable data collection pipeline.

Responsibilities:

1. Retrieve monitoring metrics.
2. Validate incoming records.
3. Handle missing values.
4. Remove invalid observations.
5. Aggregate metrics into appropriate time windows.
6. Store historical observations.

Create a consistent dataset schema.

Suggested fields:

timestamp
service_name
cpu_utilization
memory_utilization
request_count
network_ingress
network_egress
average_latency
error_rate
instance_count

Use Pandas and NumPy for preprocessing.

Never generate fake production metrics and present them as actual GCP measurements.

Synthetic data may be used for initial model development and testing, but must be clearly identified.

Module 3: AI-Based Anomaly Detection

Model: Isolation Forest.

Objective: Identify unusual infrastructure behaviour.

Input features:

- CPU utilisation.
- Memory utilisation.
- Request count.
- Network traffic.
- Application latency.
- Error rate.

Output:

{
  "anomaly_detected": true,
  "severity": "high",
  "reason": "Unusual CPU utilisation",
  "confidence": null
}

Do not treat Isolation Forest anomaly scores as calibrated probabilities.

Evaluate the model using:

- Precision.
- Recall.
- F1-score.
- Confusion matrix.
- False-positive rate.

Compare the model against a simple threshold-based baseline.

Module 4: Resource Prediction

Primary model: XGBoost.

Optional model: LSTM for time-series forecasting.

Objective: Predict future infrastructure requirements.

Input:

- Historical CPU utilisation.
- Historical memory utilisation.
- Request count.
- Network traffic.
- Time-based features.

Output:

- Predicted CPU utilisation.
- Predicted memory utilisation.
- Expected application traffic.

Prediction horizons should initially include:

- 15 minutes.
- 30 minutes.
- 60 minutes.

Evaluate using:

- MAE.
- RMSE.
- MAPE where appropriate.

Use chronological train-validation-test splitting to avoid data leakage.

Compare the prediction model with a simple historical-average or persistence baseline.

Module 5: Cost Analysis Engine

Objective: Estimate infrastructure expenditure and identify potential savings.

Responsibilities:

- Track cloud resource consumption.
- Estimate current infrastructure costs.
- Compare alternative configurations.
- Calculate estimated savings.
- Identify expensive resource configurations.

Use actual GCP pricing information or verified billing exports.

Keep estimated costs separate from actual billed costs.

Do not hardcode pricing values throughout the application.

Create a central configuration for pricing assumptions and document their source and date.

Suggested output:

{
  "current_estimated_cost": 5000,
  "recommended_estimated_cost": 3500,
  "estimated_savings": 1500,
  "savings_percentage": 30
}

The above values are illustrative only.

6. AI Optimisation Agent

Use LangGraph to implement the optimisation workflow.

The agent must combine:

1. Monitoring information.
2. Anomaly detection results.
3. Resource prediction results.
4. Cost analysis.
5. Infrastructure constraints.

Agent workflow:

        Monitoring Data
              |
              v
       Anomaly Detection
              |
              v
       Resource Prediction
              |
              v
         Cost Analysis
              |
              v
        AI Orchestrator
              |
              v
      Recommendation Agent
              |
              v
       Policy Validation
              |
              v
       Human Approval
              |
              v
       Scaling Operation

The agent should generate recommendations such as:

- Reduce minimum instance allocation.
- Increase maximum instance allocation.
- Adjust CPU allocation.
- Investigate memory pressure.
- Investigate unusual traffic.
- Review expensive infrastructure configurations.

Every recommendation must include:

- Identified problem.
- Supporting metrics.
- Proposed action.
- Expected performance impact.
- Estimated financial impact.
- Confidence or uncertainty information.
- Potential operational risks.

The LLM must not independently invent infrastructure metrics or pricing information.

Use structured outputs and validate all recommendations.

7. Dashboard Development

Use Streamlit.

Create the following dashboard sections.

A. Overview

Display:

- Total monitored services.
- Current CPU utilisation.
- Current memory utilisation.
- Total requests.
- Average application latency.
- Current estimated infrastructure expenditure.

B. Infrastructure Monitoring

Display:

- CPU utilisation graph.
- Memory utilisation graph.
- Network traffic graph.
- Request traffic graph.
- Instance count over time.

C. Anomaly Detection

Display:

- Detected anomalies.
- Severity.
- Detection timestamp.
- Anomaly explanation.
- Historical anomaly trends.

D. Resource Prediction

Display:

- Predicted CPU utilisation.
- Predicted memory requirements.
- Expected traffic.
- Historical versus predicted metrics.

E. Cost Optimisation

Display:

- Current estimated expenditure.
- Alternative configuration costs.
- Potential savings.
- Cost trends.

F. AI Recommendations

Display:

- AI-generated recommendations.
- Supporting evidence.
- Risk assessment.
- Expected savings.
- Approval status.

G. Infrastructure Actions

Display:

- Pending actions.
- Approved actions.
- Rejected actions.
- Execution history.

8. GCP Deployment Architecture

Deploy the project using Google Cloud Platform.

Recommended services:

Service| Responsibility
Cloud Run| Host the FastAPI application
Cloud Run| Host the Streamlit dashboard or background services
Cloud Monitoring| Infrastructure metrics
BigQuery| Historical metrics and analytics
Cloud Storage| Model and dataset storage
Pub/Sub| Asynchronous event processing
Vertex AI| Gemini model access and optional ML workflows
Artifact Registry| Docker image storage
Cloud Build| Automated deployment

Use Docker for application packaging.

Use Cloud Run autoscaling for the application services.

Use Application Default Credentials and service accounts for authentication.

Never commit service account JSON keys, API keys or credentials to GitHub.

Prefer least-privilege IAM permissions.

9. Repository Structure

Maintain the following modular repository structure:

AutoCloud-AI/
│
├── app/
│   ├── main.py
│   ├── config.py
│   │
│   ├── api/
│   │   ├── monitoring.py
│   │   ├── prediction.py
│   │   ├── anomaly.py
│   │   └── recommendations.py
│   │
│   ├── dashboard/
│   │   ├── home.py
│   │   ├── monitoring.py
│   │   ├── anomalies.py
│   │   ├── prediction.py
│   │   └── optimisation.py
│   │
│   ├── data/
│   │   ├── collector.py
│   │   ├── processor.py
│   │   └── storage.py
│   │
│   ├── models/
│   │   ├── anomaly_detector.py
│   │   ├── resource_predictor.py
│   │   └── cost_analyser.py
│   │
│   ├── agents/
│   │   ├── orchestrator.py
│   │   ├── recommendation_agent.py
│   │   └── validation.py
│   │
│   ├── services/
│   │   ├── gcp_monitoring.py
│   │   ├── bigquery_service.py
│   │   ├── cloudrun_service.py
│   │   └── vertex_service.py
│   │
│   └── utils/
│       ├── logging.py
│       └── metrics.py
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── synthetic/
│
├── notebooks/
│   ├── exploratory_analysis.ipynb
│   ├── anomaly_detection.ipynb
│   └── resource_prediction.ipynb
│
├── models/
│
├── tests/
│
├── infrastructure/
│   ├── Dockerfile
│   └── cloudbuild.yaml
│
├── docs/
│   ├── architecture.md
│   └── methodology.md
│
├── requirements.txt
├── .env.example
├── .gitignore
├── Dockerfile
├── README.md
└── CLAUDE.md

Create additional files only when required.

10. Security and Reliability

Follow these requirements:

- Use environment variables for configuration.
- Never expose secrets in source code.
- Use IAM-based authentication.
- Apply least-privilege access.
- Validate all API inputs.
- Implement exception handling.
- Maintain structured application logs.
- Implement API authentication where appropriate.
- Validate scaling actions before execution.
- Maintain an audit log of infrastructure changes.

Initially, all infrastructure modification operations must require explicit human approval.

Never allow the LLM to execute arbitrary shell commands or unrestricted cloud operations.

Implement limits for minimum and maximum instance counts.

11. Testing and Evaluation

Testing must cover:

1. Data collection accuracy.
2. Data preprocessing correctness.
3. Anomaly detection performance.
4. Resource prediction performance.
5. Cost estimation correctness.
6. Recommendation validation.
7. API reliability.
8. Cloud deployment functionality.

Compare the infrastructure before and after optimisation.

Important evaluation metrics:

Category| Evaluation
Anomaly Detection| Precision, Recall, F1
Prediction| MAE, RMSE
Cloud Performance| p50, p95, p99 latency
Infrastructure| CPU and memory utilisation
Application| Request throughput and error rate
Cost| Actual and estimated expenditure
Optimisation| Savings and performance impact

Never claim cost savings without experimental evidence.

12. Development Phases

Implement the project incrementally.

Phase 1: Environment Setup

- Create GCP project.
- Configure billing and budget alerts.
- Enable necessary APIs.
- Configure IAM.
- Set up Python environment.
- Create GitHub repository.

Phase 2: Initial Cloud Deployment

- Develop a sample FastAPI application.
- Containerise with Docker.
- Deploy on Cloud Run.
- Verify application accessibility.
- Generate sample requests.

Phase 3: Monitoring Pipeline

- Connect Cloud Monitoring.
- Retrieve supported metrics.
- Process monitoring data.
- Store data in BigQuery.

Phase 4: Machine Learning

- Develop Isolation Forest.
- Develop XGBoost prediction model.
- Evaluate models.
- Save trained models.

Phase 5: Cost Analysis

- Integrate billing information where available.
- Develop cost estimation logic.
- Compare infrastructure configurations.

Phase 6: AI Agent

- Implement LangGraph workflow.
- Integrate Gemini through Vertex AI.
- Generate structured recommendations.
- Implement policy validation.

Phase 7: Dashboard

- Develop Streamlit interface.
- Integrate FastAPI.
- Visualise infrastructure metrics.
- Display AI recommendations.

Phase 8: Optimisation Actions

- Implement human approval.
- Integrate supported GCP scaling operations.
- Maintain action logs.
- Test rollback and failure handling.

Phase 9: Final Evaluation

- Conduct experiments.
- Compare baseline and optimised infrastructure.
- Evaluate cost and performance.
- Document findings.

13. Coding Guidelines for Claude Code

When developing this project, follow these instructions:

1. Work incrementally, one development phase at a time.
2. Do not generate the entire application in a single response.
3. Explain the purpose of each module before implementing it.
4. Use modular and reusable Python code.
5. Follow PEP 8 coding standards.
6. Add type hints and meaningful docstrings.
7. Implement proper exception handling.
8. Write unit tests for important functions.
9. Keep cloud configuration separate from application logic.
10. Avoid unnecessary dependencies.
11. Prefer free-tier or low-cost GCP services where practical.
12. Do not deploy expensive GPU resources without explicit approval.
13. Never execute infrastructure-changing operations without explicit approval.
14. Maintain README.md with installation and deployment instructions.
15. Update documentation whenever the architecture changes.
16. Do not invent GCP API methods or unsupported metrics.
17. Verify current GCP service capabilities and pricing before implementation.
18. Never expose credentials or sensitive infrastructure information.

Before implementing a new module, inspect the existing repository and reuse existing components wherever possible.

Do not overwrite working code without understanding its functionality.

14. Expected Final Outcome

The final system should demonstrate:

- Real GCP infrastructure integration.
- Cloud-native application deployment.
- Automated infrastructure monitoring.
- Machine Learning-based anomaly detection.
- Predictive resource analysis.
- AI-powered optimisation recommendations.
- Cost analysis.
- Interactive dashboard.
- Human-approved infrastructure scaling.
- Experimental evaluation.

The project should be suitable for an MSc Artificial Intelligence portfolio and demonstrate practical knowledge of AI Engineering, Cloud Computing, MLOps and intelligent infrastructure management.

15. Instructions for Starting Development

When Claude Code starts working on this repository:

FIRST:

1. Inspect the existing project directory.
2. Read this CLAUDE.md file.
3. Identify existing files and dependencies.
4. Explain the proposed implementation architecture.
5. Identify missing GCP configuration requirements.

THEN:
Begin with Phase 1 only.

Do not jump directly to ML models or AI agents.

The first milestone is to successfully deploy a simple FastAPI application on Google Cloud Run using Docker.

After successful deployment, proceed to infrastructure monitoring and subsequent phases.

Project principle: Build a working, measurable and cost-conscious cloud AI system rather than a collection of disconnected demonstrations.