# GlucoVision
### Explainable AI for Diabetic Retinopathy Screening in Rural India

GlucoVision is an AI-powered diabetic retinopathy screening platform designed to support early detection and improve healthcare coordination in rural and underserved communities.

The platform combines deep learning-based retinal image analysis, Explainable AI, and a connected healthcare network to support patient screening, hospital referrals, and follow-up care.

## Problem Statement

Access to timely diabetic retinopathy screening and specialist care remains a challenge in rural areas. Limited access to ophthalmologists and fragmented healthcare coordination can delay further evaluation and treatment.

GlucoVision aims to address these challenges by integrating AI-assisted screening with a structured healthcare network connecting health centres and main hospitals.

## Key Features

**AI-Based Retinal Screening**
- Analyses retinal fundus images using a trained deep learning model.
- Generates screening predictions to support further clinical evaluation.

**Explainable AI with Grad-CAM**
- Generates heatmaps highlighting image regions that contribute to model predictions.
- Helps users examine and understand model behaviour.

**Healthcare Network Management**
- Organizes healthcare facilities through a hierarchy: Super Admin → Main Hospital → Health Centres.
- Supports management of connected healthcare facilities.

**Patient Registration and Screening**
- Supports patient registration and retinal screening at health centres.
- Maintains associated screening records for authorized users.

**Referral and Clinical Review**
- Facilitates referrals from health centres to their associated main hospitals.
- Supports hospital-based review and documentation of clinical decisions.

**Appointment and Follow-Up Management**
- Supports appointment tracking and follow-up workflows.
- Helps identify missed appointments and coordinate further care.

## System Architecture

- **Frontend:** React, Vite, JavaScript
- **Backend:** Python, FastAPI
- **Database:** SQLite, SQLAlchemy
- **Deep Learning:** TensorFlow, Keras
- **Explainable AI:** Grad-CAM

## Technology Stack

| Component | Technologies |
|---|---|
| Frontend | React, Vite, JavaScript |
| Backend | Python, FastAPI |
| Database | SQLite, SQLAlchemy |
| AI Model | TensorFlow, Keras |
| Explainability | Grad-CAM |
| Version Control | Git, GitHub |

## Application Workflow

1. A patient is registered at a health centre.
2. A retinal fundus image is submitted for AI-assisted screening.
3. The trained model generates a screening prediction.
4. Grad-CAM provides a visual explanation of the model's output.
5. Cases requiring further evaluation can be referred to the associated main hospital.
6. Hospital staff review referrals and document clinical decisions.
7. Appointment and follow-up workflows help coordinate continued care.

## Installation and Setup

### Prerequisites

- Python 3.10
- Node.js and npm
- Git

### 1. Clone the Repository

```bash
git clone https://github.com/saghanarajmohan/GlucoVision.git
cd GlucoVision
```

### 2. Set Up the Backend

Create and activate a virtual environment.

```bash
python -m venv .venv
```

On Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

### 3. Set Up the Frontend

Open a terminal in the frontend directory.

```bash
cd frontend
npm install
```

### 4. Run the Application

Start the backend from the project root:

```bash
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

In a separate terminal, start the frontend:

```bash
cd frontend
npm run dev
```

Open the local URL displayed in the frontend terminal to access the application.

*Note: Configure the required environment variables and frontend API address according to the project setup before running the application.*

## Explainable AI

GlucoVision incorporates **Gradient-weighted Class Activation Mapping (Grad-CAM)** to visualize image regions that contribute to a model's prediction.

These visualizations help users examine model behaviour but do not independently establish a diagnosis or guarantee prediction accuracy.

## Future Scope

- Evaluation on larger and more diverse retinal image datasets.
- Improved model robustness across different imaging conditions.
- Enhanced follow-up coordination and healthcare accessibility.
- Further clinical validation and security improvements.

## Disclaimer

GlucoVision is an academic project developed for research and educational purposes. It is intended to support screening workflows and is not a substitute for professional medical diagnosis or clinical judgement.

---

**GlucoVision — Bringing Explainable AI Closer to Rural Eye Care.**
