# Project Configuration — Single Project of Record (Hybrid Setup)

This application uses a hybrid project configuration:
*   **Firebase Authentication & Firestore**: **`inclusia-150123`**
*   **Firebase Storage**: **`inclusia-501005-resources`** (hosted under GCP project `inclusia-501005`)

Do NOT change `FIREBASE_PROJECT_ID` or bucket configuration without updating ALL of:
1. Cloud Run environment variables
2. Local developer configuration (`backend/.env`)
3. Service account credentials (`firebase/serviceAccountKey.json`, if used locally)
4. This document

## Consolidated Firebase Settings
*   **Firebase Project ID**: `inclusia-150123`
*   **Firebase Storage Bucket**: `inclusia-501005-resources`
*   **Cloud Run Service Region**: `asia-southeast2` (hosted under GCP project `inclusia-501005`)

## Security & Cross-Project Credentials Policy
Local environment configuration `.env` and local Firebase credential file `firebase/serviceAccountKey.json` are excluded from container builds via `.gcloudignore`. 

In production, because the Cloud Run instance runs in a separate GCP project (`inclusia-501005`), the backend **cannot** use the default Compute Engine service account (ADC) to access resources in the `inclusia-150123` Firebase project. Therefore, the backend must be explicitly configured with `FIREBASE_CREDENTIALS` (containing the service account JSON key of `inclusia-150123`) in the Cloud Run service environment.

We have granted the `inclusia-150123` service account (`firebase-adminsdk-fbsvc@inclusia-150123.iam.gserviceaccount.com`) the **`roles/storage.objectAdmin`** IAM role on the `inclusia-501005-resources` Storage bucket, permitting cross-project uploads.
