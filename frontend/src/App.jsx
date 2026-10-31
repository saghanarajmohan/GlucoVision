import { useCallback, useEffect, useRef, useState } from "react";
import NetworkDashboard from "./NetworkDashboard";
import AuthenticatedImage from "./AuthenticatedImage";
import "./App.css";

function App() {
  // ============================================================
  // AUTH
  // ============================================================

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [user, setUser] = useState(null);
  const [loginError, setLoginError] = useState(null);
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [registeredPatients, setRegisteredPatients] = useState([]);
  const [localAppointments, setLocalAppointments] = useState([]);
  const [centreScreenings, setCentreScreenings] = useState([]);
  const [centreScreeningsError, setCentreScreeningsError] = useState(null);
  const [expandedCentreReport, setExpandedCentreReport] = useState(null);
  const [activeCentreTab, setActiveCentreTab] = useState("register");
  const [expandedPatientHistory, setExpandedPatientHistory] = useState(null);
  const [centreRecordsLoading, setCentreRecordsLoading] = useState(true);
  const [notificationsLoading, setNotificationsLoading] = useState(true);
  const [notificationsError, setNotificationsError] = useState(null);
  const [openingCentrePdf, setOpeningCentrePdf] = useState(null);
  const [centrePatientSearch, setCentrePatientSearch] = useState("");
  const [existingPatientSearch, setExistingPatientSearch] = useState("");
  const [appointmentPatientId, setAppointmentPatientId] = useState("");
  const [appointmentWhen, setAppointmentWhen] = useState("");
  const [appointmentReason, setAppointmentReason] = useState("Follow-up");
  const [appointmentNotes, setAppointmentNotes] = useState("");
  const [appointmentMessage, setAppointmentMessage] = useState("");
  const [rescheduleId, setRescheduleId] = useState(null);
  const [rescheduleWhen, setRescheduleWhen] = useState("");

  // ============================================================
  // PATIENT
  // ============================================================

  const [patientName, setPatientName] = useState("");
  const [patientAge, setPatientAge] = useState("");
  const [patientSex, setPatientSex] = useState("");
  const [patientPhone, setPatientPhone] = useState("");
  const [patient, setPatient] = useState(null);
  const [isRegistering, setIsRegistering] = useState(false);
  const [patientError, setPatientError] = useState(null);
  const [patientRegisteredMessage, setPatientRegisteredMessage] = useState(null);
  const registrationInProgress = useRef(false);

  // ============================================================
  // SCREENING
  // ============================================================

  const [selectedImage, setSelectedImage] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [result, setResult] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  // ============================================================
  // HOSPITAL SUBMISSION
  // ============================================================

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submissionMessage, setSubmissionMessage] = useState(null);

  // ============================================================
  // HOSPITAL CASES
  // ============================================================

  const [hospitalCases, setHospitalCases] = useState([]);
  const [isLoadingCases, setIsLoadingCases] = useState(false);
  const [hospitalCasesError, setHospitalCasesError] = useState(null);

  const [hospitalView, setHospitalView] = useState(null);

  // ============================================================
  // SELECTED CASE
  // ============================================================

  const [selectedCase, setSelectedCase] = useState(null);

  // ============================================================
  // DOCTOR REVIEW
  // ============================================================

  const [consultedDoctor, setConsultedDoctor] = useState("");
  const [doctorNotes, setDoctorNotes] = useState("");

  // ============================================================
  // APPOINTMENT
  // ============================================================

  const [appointmentDate, setAppointmentDate] = useState("");
  const [appointmentTime, setAppointmentTime] = useState("");

  const [isSavingReview, setIsSavingReview] = useState(false);
  const [reviewMessage, setReviewMessage] = useState(null);
  const [reviewError, setReviewError] = useState(null);

  // ============================================================
  // FOLLOW-UPS
  // ============================================================

  const [showFollowUps, setShowFollowUps] = useState(false);
  const [followUps, setFollowUps] = useState([]);
  const [isLoadingFollowUps, setIsLoadingFollowUps] = useState(false);
  const [followUpError, setFollowUpError] = useState(null);
  const [followUpMessage, setFollowUpMessage] = useState(null);

  // ============================================================
  // HELPERS
  // ============================================================

  const isNoDR = (prediction) => {
    if (!prediction) return false;

    const normalized = prediction
      .toString()
      .trim()
      .toLowerCase();

    return (
      normalized === "no diabetic retinopathy" ||
      normalized === "no dr" ||
      normalized === "no_diabetic_retinopathy" ||
      normalized === "0"
    );
  };

  const authHeaders = useCallback((extra = {}) => ({
    ...extra,
    ...(user?.session_token
      ? { Authorization: `Bearer ${user.session_token}` }
      : {}),
  }), [user]);

  useEffect(() => {
    if (!['HEALTH_CENTRE', 'HEALTH_CENTRE_USER', 'HEALTH_CENTRE_STAFF'].includes(user?.role) || !user.health_centre_id) return;
    let active = true;
    const loadNotifications = () => {
      fetch(`/api/health-centre/${user.health_centre_id}/notifications`, {
        headers: authHeaders(),
      })
        .then((response) => { if (!response.ok) throw new Error("Unable to load health-centre alerts."); return response.json(); })
        .then((data) => { if (active) { setNotifications(data.notifications || []); setNotificationsError(null); } })
        .catch((error) => { if (active) { setNotificationsError(error.message); setNotifications([]); } })
        .finally(() => { if (active) setNotificationsLoading(false); });
    };
    loadNotifications();
    const timer = window.setInterval(loadNotifications, 30000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [user, authHeaders]);

  useEffect(() => {
    if (!['HEALTH_CENTRE', 'HEALTH_CENTRE_USER', 'HEALTH_CENTRE_STAFF'].includes(user?.role) || !user.health_centre_id) return;
    let active = true;
    const loadReports = () => fetch(`/api/health-centre/${user.health_centre_id}/screenings`, { headers: authHeaders() })
      .then(async (response) => { if (!response.ok) throw new Error("Unable to load submitted screening reports."); return response.json(); })
      .then((data) => { if (active) { setCentreScreenings(data.screenings || []); setCentreScreeningsError(null); } })
      .catch((error) => { if (active) setCentreScreeningsError(error.message); })
      .finally(() => { if (active) setCentreRecordsLoading(false); });
    loadReports();
    const timer = window.setInterval(loadReports, 30000);
    return () => { active = false; window.clearInterval(timer); };
  }, [user, authHeaders]);

  useEffect(() => {
    if (!['HEALTH_CENTRE', 'HEALTH_CENTRE_USER', 'HEALTH_CENTRE_STAFF'].includes(user?.role) || !user.health_centre_id) return;
    fetch("/api/appointments", { headers: authHeaders() })
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then((data) => setLocalAppointments(data.appointments || []))
      .catch(() => setLocalAppointments([]));
  }, [user, authHeaders]);

  useEffect(() => {
    if (!['HEALTH_CENTRE', 'HEALTH_CENTRE_USER', 'HEALTH_CENTRE_STAFF'].includes(user?.role) || !user.health_centre_id) return;
    fetch(`/api/patients?health_centre_id=${user.health_centre_id}`, { headers: authHeaders() })
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then((data) => setRegisteredPatients((current) => {
        const merged = new Map((data.patients || []).map((item) => [item.id, item]));
        current.forEach((item) => merged.set(item.id, item));
        return [...merged.values()].sort((left, right) => left.name.localeCompare(right.name));
      }))
      .catch(() => setRegisteredPatients([]))
      .finally(() => setCentreRecordsLoading(false));
  }, [user, authHeaders]);

  const normalizeCase = (item) => {
    return {
      ...item,

      patient_name:
        item.patient?.name ||
        item.patient_name ||
        "-",

      patient_code:
        item.patient?.patient_code ||
        item.patient_code ||
        `PAT-${item.patient?.id || item.patient_id || "-"}`,

      patient_id:
        item.patient?.id ||
        item.patient_id ||
        null,

      age:
        item.patient?.age ??
        item.age ??
        "-",

      sex:
        item.patient?.sex ||
        item.sex ||
        "-",

      health_centre:
        item.health_centre?.name ||
        item.health_centre ||
        "-",

      health_centre_id:
        item.health_centre?.id ||
        item.health_centre_id ||
        null,

      appointment:
        item.appointment || null,

      gradcam_image_path:
        item.gradcam_image ||
        item.gradcam_image_path ||
        item.heatmap_path ||
        null,
    };
  };

  const formatAppointmentTime = (appointment) => {
    if (!appointment) return "-";
    return appointment.appointment_datetime
      ? new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: appointment.appointment_time_zone || undefined }).format(new Date(appointment.appointment_datetime))
      : "-";
  };

  // ============================================================
  // LOGIN
  // ============================================================

  const handleLogin = async (event) => {
    event.preventDefault();

    setIsLoggingIn(true);
    setLoginError(null);

    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          username,
          password,
        }),
      });

      const responseText = await response.text();
      let data = {};

      if (responseText.trim()) {
        try {
          data = JSON.parse(responseText);
        } catch {
          throw new Error(
            `The server returned an invalid response (HTTP ${response.status}). Check that the backend is running at http://127.0.0.1:8000.`
          );
        }
      } else {
        throw new Error(
          `The server returned an empty response (HTTP ${response.status}). Check that the backend is running at http://127.0.0.1:8000.`
        );
      }

      if (!response.ok) {
        throw new Error(data.detail || "Login failed.");
      }

      const loggedInUser = data.user || data;

      setUser(loggedInUser);
      setPassword("");
    } catch (err) {
      setLoginError(
        err.message || "Unable to connect to the server."
      );
    } finally {
      setIsLoggingIn(false);
    }
  };

  // ============================================================
  // LOGOUT
  // ============================================================

  const handleLogout = () => {
    setUser(null);

    setUsername("");
    setPassword("");

    setPatientName("");
    setPatientAge("");
    setPatientSex("");
    setPatient(null);
    setPatientError(null);

    setSelectedImage(null);
    setSelectedFile(null);
    setResult(null);
    setError(null);

    setSubmissionMessage(null);

    setHospitalCases([]);
    setSelectedCase(null);
    setHospitalCasesError(null);
    setHospitalView(null);

    setConsultedDoctor("");
    setDoctorNotes("");

    setAppointmentDate("");
    setAppointmentTime("");

    setReviewMessage(null);
    setReviewError(null);

    setShowFollowUps(false);
    setFollowUps([]);
    setFollowUpError(null);
    setFollowUpMessage(null);
  };

  // ============================================================
  // PATIENT REGISTRATION
  // ============================================================

  const handlePatientRegistration = async (event) => {
    event.preventDefault();
    if (registrationInProgress.current) return;
    registrationInProgress.current = true;

    setIsRegistering(true);
    setPatientError(null);

    try {
      const healthCentreId =
        user?.health_centre_id ||
        user?.healthCentreId ||
        user?.id;

      if (!healthCentreId) {
        throw new Error(
          "Health Centre ID is missing. Please log in again."
        );
      }

      /*
       * IMPORTANT:
       *
       * The backend expects:
       *
       * POST /api/patients?health_centre_id=1
       *
       * with patient information inside the JSON body:
       *
       * {
       *   "name": "...",
       *   "age": 67,
       *   "sex": "Male"
       * }
       */

      const response = await fetch(
        `/api/patients?health_centre_id=${encodeURIComponent(
          healthCentreId
        )}`,
        {
          method: "POST",

          headers: {
            ...authHeaders(),
            "Content-Type": "application/json",
          },

          body: JSON.stringify({
            name: patientName.trim(),
            age: Number(patientAge),
            sex: patientSex,
            phone: patientPhone.trim() || null,
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        let errorMessage = "Patient registration failed.";

        if (typeof data.detail === "string") {
          errorMessage = data.detail;
        } else if (Array.isArray(data.detail)) {
          errorMessage = data.detail
            .map((item) => item.msg || "Invalid input")
            .join(", ");
        }

        throw new Error(errorMessage);
      }

      /*
       * Backend normally returns:
       *
       * {
       *   message: "...",
       *   patient: {...}
       * }
       *
       * Support both formats.
       */

      const registeredPatientData = data.patient || data;
      const registeredPatient = {
        ...registeredPatientData,
        id: registeredPatientData.patient_id || registeredPatientData.id,
        patient_id: registeredPatientData.patient_id || registeredPatientData.id,
        health_centre_id: registeredPatientData.health_centre_id || Number(healthCentreId),
      };

      setPatient(registeredPatient);
      setRegisteredPatients((current) => [registeredPatient, ...current.filter((item) => item.id !== registeredPatient.id)]);
      setPatientError(null);
      setPatientRegisteredMessage(`Patient registered successfully. Patient ID ${registeredPatient.patient_code || registeredPatient.id}. You can screen this patient now.`);

      // Reset screening state for the newly registered patient
      setSelectedImage(null);
      setSelectedFile(null);
      setResult(null);
      setError(null);
      setSubmissionMessage(null);

      // Clear registration form
      setPatientName("");
      setPatientAge("");
      setPatientSex("");
      setPatientPhone("");

    } catch (err) {
      setPatientError(
        err.message ||
          "Unable to register the patient."
      );
    } finally {
      registrationInProgress.current = false;
      setIsRegistering(false);
    }
  };

  const selectPatientForScreening = (patientId) => {
    const selected = registeredPatients.find((item) => String(item.id) === String(patientId));
    if (!selected) return;
    setPatient(selected);
    setSelectedImage(null);
    setSelectedFile(null);
    setResult(null);
    setError(null);
    setSubmissionMessage(null);
    setPatientError(null);
    setPatientRegisteredMessage(null);
  };

  const startScreeningForPatient = (selected) => {
    if (!selected) return;
    selectPatientForScreening(selected.id);
    setActiveCentreTab("register");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  // ============================================================
  // IMAGE SELECTION
  // ============================================================

  const handleImageChange = (event) => {
    const file = event.target.files[0];

    if (!file) return;

    setSelectedFile(file);
    setSelectedImage(URL.createObjectURL(file));

    setResult(null);
    setError(null);
    setSubmissionMessage(null);
  };

  // ============================================================
  // AI ANALYSIS
  // ============================================================

  const handleAnalyze = async () => {
    if (!patient) {
      setError(
        "Please register a patient before uploading a retinal image."
      );
      return;
    }

    if (!selectedFile) {
      setError("Please select a retinal image.");
      return;
    }

    setIsLoading(true);
    setError(null);
    setResult(null);
    setSubmissionMessage(null);

    const formData = new FormData();
    formData.append("file", selectedFile);

    const patientId =
      patient.patient_id ||
      patient.id;

    try {
      const response = await fetch(
        `/api/predict?patient_id=${patientId}`,
        {
          method: "POST",
          headers: authHeaders(),
          body: formData,
        }
      );

      const data = await response.json();

      if (data.status === "rejected") {
        setError(
          data.reason ||
            "The image was rejected."
        );
        return;
      }

      if (!response.ok) {
        throw new Error(
          data.detail ||
            "Prediction failed."
        );
      }

      setResult(data);
      if (data.screening_id) {
        const savedReport = {
          screening_id: data.screening_id,
          patient_id: data.patient_id || patientId,
          patient_name: data.patient_name || patient?.name,
          patient_code: data.patient_code || patient?.patient_code,
          patient_age: patient?.age,
          patient_sex: patient?.sex,
          patient_phone: patient?.phone,
          screening_date: new Date().toISOString(),
          prediction: data.prediction,
          confidence: data.confidence,
          probabilities: data.probabilities || {},
          submitted_to_hospital: data.submitted_to_hospital || "NO",
          review_status: data.review_status || "PENDING",
          original_report_pdf_available: Boolean(data.original_report_pdf_path),
          original_pdf_url: data.original_report_pdf_path || null,
          original_image_url: data.original_image_url || (data.screening_id ? `/api/screening/${data.screening_id}/original-image` : null),
          gradcam_image_path: data.gradcam_image_path || data.heatmap_path || null,
          clinical_disposition: null,
          appointment: null,
        };
        setCentreScreenings((current) => [savedReport, ...current.filter((item) => item.screening_id !== savedReport.screening_id)]);
      }

    } catch (err) {
      setError(
        err.message ||
          "Unable to connect to the prediction server."
      );
    } finally {
      setIsLoading(false);
    }
  };

  // ============================================================
  // PRINT REPORT
  // ============================================================

  const handlePrintReport = async () => {
    if (!result?.screening_id || !user?.session_token) {
      setError("Save a screening report before opening its original PDF.");
      return;
    }
    try {
      const response = await fetch(`/api/screening/${result.screening_id}/original-pdf`, {
        headers: { Authorization: `Bearer ${user.session_token}` },
      });
      if (!response.ok) throw new Error((await response.json()).detail || "Unable to open the original screening PDF.");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const opened = window.open(url, "_blank", "noopener,noreferrer");
      if (!opened) { const link = document.createElement("a"); link.href = url; link.download = `GlucoVision-report-${result.screening_id}.pdf`; link.click(); }
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) { setError(error.message); }
  };

  const openSavedCentrePdf = async (screeningId) => {
    setOpeningCentrePdf(screeningId);
    setError(null);
    try {
      const response = await fetch(`/api/screening/${screeningId}/original-pdf`, { headers: authHeaders() });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "The original screening PDF is unavailable.");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const opened = window.open(url, "_blank", "noopener,noreferrer");
      if (!opened) {
        const link = document.createElement("a");
        link.href = url;
        link.download = `GlucoVision_Screening_Report_${screeningId}.pdf`;
        link.click();
      }
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (openError) {
      setCentreScreeningsError(openError.message);
    } finally {
      setOpeningCentrePdf(null);
    }
  };

  // ============================================================
  // SUBMIT TO HOSPITAL
  // ============================================================

  const handleSubmitToHospital = async () => {
    if (!result?.screening_id) {
      setError(
        "No completed screening is available for submission."
      );
      return;
    }

    if (isNoDR(result.prediction)) {
      setSubmissionMessage(
        "Hospital referral is not required for No Diabetic Retinopathy."
      );
      return;
    }

    setIsSubmitting(true);
    setError(null);
    setSubmissionMessage(null);

    try {
      const response = await fetch(
        `/api/screening/${result.screening_id}/submit`,
        {
          method: "POST",
          headers: authHeaders(),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ||
            "Unable to submit the screening to the hospital."
        );
      }

      if (data.submitted === false) {
        setSubmissionMessage(
          data.message ||
            "Hospital referral is not required."
        );

        return;
      }

      setSubmissionMessage(
        "Screening submitted to the hospital successfully."
      );

      setResult((previous) => ({
        ...previous,
        status:
          data.status ||
          "SUBMITTED",
        submitted_to_hospital:
          data.submitted_to_hospital ||
          "YES",
      }));
      setCentreScreenings((current) => current.map((report) => report.screening_id === result.screening_id
        ? { ...report, submitted_to_hospital: "YES", submitted_at: data.submitted_at || new Date().toISOString(), referral_status: "REFERRED" }
        : report));

    } catch (err) {
      setError(
        err.message ||
          "Unable to submit the screening."
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  // ============================================================
  // LOAD HOSPITAL CASES
  // ============================================================

  const loadHospitalCases = async (category) => {
    setIsLoadingCases(true);
    setHospitalCasesError(null);

    try {
      const response = await fetch(
        `/api/hospital/cases?category=${category}`
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ||
            "Unable to load hospital cases."
        );
      }

      const normalizedCases = (
        data.cases || []
      ).map(normalizeCase);

      setHospitalCases(normalizedCases);
      setHospitalView(category);
      setSelectedCase(null);

      setConsultedDoctor("");
      setDoctorNotes("");
      setAppointmentDate("");
      setAppointmentTime("");

      setReviewMessage(null);
      setReviewError(null);

      return normalizedCases;

    } catch (err) {
      setHospitalCasesError(
        err.message ||
          "Unable to load hospital cases."
      );

      return [];
    } finally {
      setIsLoadingCases(false);
    }
  };

  // ============================================================
  // SUBMITTED CASES
  // ============================================================

  const handleViewCases = async () => {
    setShowFollowUps(false);
    setFollowUps([]);
    setFollowUpError(null);
    setFollowUpMessage(null);

    await loadHospitalCases("submitted");

    setTimeout(() => {
      const section =
        document.getElementById(
          "hospital-cases-section"
        );

      if (section) {
        section.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }
    }, 150);
  };

  // ============================================================
  // PATIENT REVIEWS
  // ============================================================

  const handleReviewPatients = async () => {
    setShowFollowUps(false);
    setFollowUps([]);
    setFollowUpError(null);
    setFollowUpMessage(null);

    await loadHospitalCases("reviewed");

    setTimeout(() => {
      const section =
        document.getElementById(
          "hospital-cases-section"
        );

      if (section) {
        section.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }
    }, 150);
  };

  // ============================================================
  // VIEW CASE DETAILS
  // ============================================================

  const handleViewCaseDetails = (caseItem) => {
    setSelectedCase(caseItem);

    setConsultedDoctor(
      caseItem.consulted_doctor || ""
    );

    setDoctorNotes(
      caseItem.doctor_notes || ""
    );

    if (caseItem.appointment?.appointment_datetime) {
      const [datePart, timePart] = caseItem.appointment.appointment_datetime.split("T");
      setAppointmentDate(datePart || "");
      setAppointmentTime((timePart || "").slice(0, 5));
    } else {
      setAppointmentDate("");
      setAppointmentTime("");
    }

    setReviewMessage(null);
    setReviewError(null);

    setTimeout(() => {
      const detailsSection =
        document.getElementById(
          "case-details"
        );

      if (detailsSection) {
        detailsSection.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }
    }, 100);
  };

  // ============================================================
  // CLOSE CASE DETAILS
  // ============================================================

  const handleCloseCaseDetails = () => {
    setSelectedCase(null);

    setConsultedDoctor("");
    setDoctorNotes("");

    setAppointmentDate("");
    setAppointmentTime("");

    setReviewMessage(null);
    setReviewError(null);
  };

  // ============================================================
  // SAVE DOCTOR REVIEW
  // ============================================================

  const handleSaveDoctorReview = async () => {
    if (!selectedCase) return;

    if (!consultedDoctor.trim()) {
      setReviewError(
        "Please enter the consulted doctor's name."
      );
      return;
    }

    if (!appointmentDate) {
      setReviewError(
        "Please select the next appointment date."
      );
      return;
    }

    if (!appointmentTime) {
      setReviewError(
        "Please select the next appointment time."
      );
      return;
    }

    setIsSavingReview(true);
    setReviewMessage(null);
    setReviewError(null);

    try {
      const appointmentDateTime =
        `${appointmentDate}T${appointmentTime}`;

      const response = await fetch(
        `/api/screening/${selectedCase.screening_id}/review`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(user?.session_token ? { Authorization: `Bearer ${user.session_token}` } : {}),
          },
          body: JSON.stringify({
            consulted_doctor:
              consultedDoctor.trim(),

            doctor_notes:
              doctorNotes.trim() || null,

            appointment_datetime:
              appointmentDateTime,

            appointment_type:
              "Hospital Consultation",
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ||
            "Unable to save doctor consultation."
        );
      }

      setReviewMessage(
        "Consultation saved and next appointment scheduled successfully."
      );

      const updatedAppointment =
        data.appointment || null;

      setSelectedCase((previous) => ({
        ...previous,

        consulted_doctor:
          consultedDoctor.trim(),

        doctor_notes:
          doctorNotes.trim() || null,

        status: "REVIEWED",

        appointment:
          updatedAppointment,
      }));

      if (hospitalView === "submitted") {
        setHospitalCases((previous) =>
          previous.filter(
            (item) =>
              item.screening_id !==
              selectedCase.screening_id
          )
        );
      } else {
        setHospitalCases((previous) =>
          previous.map((item) =>
            item.screening_id ===
            selectedCase.screening_id
              ? {
                  ...item,

                  consulted_doctor:
                    consultedDoctor.trim(),

                  doctor_notes:
                    doctorNotes.trim() || null,

                  status: "REVIEWED",

                  appointment:
                    updatedAppointment,
                }
              : item
          )
        );
      }

    } catch (err) {
      setReviewError(
        err.message ||
          "Unable to save doctor consultation."
      );
    } finally {
      setIsSavingReview(false);
    }
  };

  // ============================================================
  // LOAD FOLLOW-UPS
  // ============================================================

  const handleManageFollowUps = async () => {
    setShowFollowUps(true);

    setFollowUpError(null);
    setFollowUpMessage(null);

    setHospitalCases([]);
    setSelectedCase(null);
    setHospitalView(null);

    setIsLoadingFollowUps(true);

    try {
      const response = await fetch(
        "/api/hospital/cases?category=followups"
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ||
            "Unable to load follow-ups."
        );
      }

      const appointments = (
        data.cases || []
      ).map(normalizeCase);

      setFollowUps(appointments);

      setTimeout(() => {
        const section =
          document.getElementById(
            "follow-ups-section"
          );

        if (section) {
          section.scrollIntoView({
            behavior: "smooth",
            block: "start",
          });
        }
      }, 150);

    } catch (err) {
      setFollowUpError(
        err.message ||
          "Unable to load follow-ups."
      );
    } finally {
      setIsLoadingFollowUps(false);
    }
  };

  // ============================================================
  // MARK APPOINTMENT ATTENDED
  // ============================================================

  const handleMarkAppointmentAttended = async (
    appointmentId
  ) => {
    if (!appointmentId) return;

    setFollowUpError(null);
    setFollowUpMessage(null);

    try {
      const response = await fetch(
        `/api/appointments/${appointmentId}/attended`,
        {
          method: "POST",
          headers: authHeaders(),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ||
            "Unable to mark appointment as attended."
        );
      }

      setFollowUpMessage(
        "Appointment marked as ATTENDED. The patient has been moved to Patient Reviews."
      );

      setFollowUps((previous) =>
        previous.filter(
          (item) =>
            item.appointment?.id !==
            appointmentId
        )
      );

    } catch (err) {
      setFollowUpError(
        err.message ||
          "Unable to mark appointment as attended."
      );
    }
  };

  // ============================================================
  // MARK APPOINTMENT MISSED
  // ============================================================

  const handleNotificationRead = async (notificationId) => {
    const response = await fetch(`/api/notifications/${notificationId}/read`, {
      method: "PATCH", headers: authHeaders(),
    });
    if (response.ok) setNotifications((items) => items.map((item) => item.id === notificationId ? { ...item, is_read: true } : item));
  };

  const handleCreateAppointment = async (event) => {
    event.preventDefault();
    setAppointmentMessage("");
    try {
      const response = await fetch("/api/appointments", {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          patient_id: Number(appointmentPatientId),
          appointment_datetime: appointmentWhen,
          appointment_type: appointmentReason,
          notes: appointmentNotes || null,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Unable to schedule appointment");
      setAppointmentMessage("Appointment scheduled successfully.");
      setLocalAppointments((rows) => [data.appointment, ...rows]);
      setAppointmentPatientId("");
      setAppointmentWhen("");
      setAppointmentNotes("");
    } catch (error) {
      setAppointmentMessage(error.message);
    }
  };

  const handleCancelAppointment = async (appointmentId) => {
    const response = await fetch(`/api/appointments/${appointmentId}`, {
      method: "PATCH",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ status: "CANCELLED" }),
    });
    if (response.ok) setLocalAppointments((rows) => rows.map((row) => row.id === appointmentId ? { ...row, status: "CANCELLED" } : row));
  };

  const handleRescheduleAppointment = async (event, appointmentId) => {
    event.preventDefault();
    const response = await fetch(`/api/appointments/${appointmentId}`, {
      method: "PATCH",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ appointment_datetime: rescheduleWhen }),
    });
    const data = await response.json();
    if (response.ok) {
      setLocalAppointments((rows) => rows.map((row) => row.id === appointmentId ? { ...row, ...data.appointment } : row));
      setRescheduleId(null);
      setAppointmentMessage("Appointment rescheduled.");
    } else setAppointmentMessage(data.detail || "Unable to reschedule appointment.");
  };

  const handleAttendLocalAppointment = async (appointmentId) => {
    const response = await fetch(`/api/appointments/${appointmentId}/attended`, { method: "POST", headers: authHeaders() });
    if (response.ok) setLocalAppointments((rows) => rows.map((row) => row.id === appointmentId ? { ...row, status: "ATTENDED" } : row));
  };

  // ============================================================
  // LOGIN SCREEN
  // ============================================================

  if (!user) {
    return (
      <div className="app">

        <header className="header">
          <div className="logo">

            <div className="logo-icon">
              G
            </div>

            <div>
              <h1>
                GlucoVision
              </h1>

              <p>
                AI-Powered Diabetic Retinopathy Screening
              </p>
            </div>

          </div>
        </header>

        <main className="main-content">

          <section className="upload-card">

            <h2>
              Sign In
            </h2>

            <p>
              Sign in to access the GlucoVision
              screening system.
            </p>

            <form onSubmit={handleLogin}>

              <div>
                <label>
                  Username
                </label>

                <input
                  type="text"
                  value={username}
                  onChange={(e) =>
                    setUsername(e.target.value)
                  }
                  placeholder="Enter username"
                  required
                />
              </div>

              <div>
                <label>
                  Password
                </label>

                <input
                  type="password"
                  value={password}
                  onChange={(e) =>
                    setPassword(e.target.value)
                  }
                  placeholder="Enter password"
                  required
                />
              </div>

              {loginError && (
                <p className="error-message">
                  {loginError}
                </p>
              )}

              <button
                type="submit"
                className="analyze-button"
                disabled={isLoggingIn}
              >
                {isLoggingIn
                  ? "Signing in..."
                  : "Sign In"}
              </button>

            </form>

          </section>

        </main>

        <footer className="footer">
          <p>
            GlucoVision • AI-assisted screening prototype
          </p>
        </footer>

      </div>
    );
  }

  // ============================================================
  // DOCTOR DASHBOARD
  // ============================================================

  if (user.role === "SUPER_ADMIN" || user.role === "HOSPITAL_ADMIN") {
    return <NetworkDashboard user={user} onLogout={handleLogout} />;
  }

  if (user.role === "DOCTOR") {
    return (
      <div className="app">

        <header className="header">

          <div className="logo">

            <div className="logo-icon">
              G
            </div>

            <div>
              <h1>
                GlucoVision
              </h1>

              <p>
                Main Hospital
              </p>
            </div>

          </div>

          <button onClick={handleLogout}>
            Logout
          </button>

        </header>

        <main className="main-content">

          <section className="hero">

            <h2>
              Hospital Dashboard
            </h2>

            <p>
              Welcome, {user.name}.
            </p>

          </section>

          {/* ==================================================
              DASHBOARD BUTTONS
          ================================================== */}

          <section className="info-section">

            <div className="info-card">

              <h3>
                Submitted Cases
              </h3>

              <p>
                Patients submitted by Health Centres
                who have not yet been attended by a
                doctor.
              </p>

              <button
                type="button"
                className="analyze-button"
                onClick={handleViewCases}
                disabled={isLoadingCases}
              >
                {isLoadingCases &&
                hospitalView === "submitted"
                  ? "Loading..."
                  : "View Submitted Cases"}
              </button>

            </div>

            <div className="info-card">

              <h3>
                Patient Reviews
              </h3>

              <p>
                Patients whose hospital appointment
                has already been attended by a doctor.
              </p>

              <button
                type="button"
                className="analyze-button"
                onClick={handleReviewPatients}
                disabled={isLoadingCases}
              >
                {isLoadingCases &&
                hospitalView === "reviewed"
                  ? "Loading..."
                  : "Review Patients"}
              </button>

            </div>

            <div className="info-card">

              <h3>
                Follow-ups
              </h3>

              <p>
                Patients with currently scheduled
                hospital appointments.
              </p>

              <button
                type="button"
                className="analyze-button"
                onClick={handleManageFollowUps}
                disabled={isLoadingFollowUps}
              >
                {isLoadingFollowUps
                  ? "Loading..."
                  : "Manage Follow-ups"}
              </button>

            </div>

            {['HEALTH_CENTRE', 'HEALTH_CENTRE_USER', 'HEALTH_CENTRE_STAFF'].includes(user?.role) && <form className="info-card" onSubmit={handleCreateAppointment}>
              <h3>Schedule an appointment</h3>
              <label>Registered patient
                <select value={appointmentPatientId} onChange={(e) => setAppointmentPatientId(e.target.value)} required>
                  <option value="">Select a patient</option>
                  {registeredPatients.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.patient_code}</option>)}
                </select>
              </label>
              <label>Clinic date and time ({user.appointment_time_zone || "Asia/Kolkata"})
                <input type="datetime-local" value={appointmentWhen} onChange={(e) => setAppointmentWhen(e.target.value)} required />
              </label>
              <label>Reason or follow-up
                <input value={appointmentReason} onChange={(e) => setAppointmentReason(e.target.value)} required />
              </label>
              <label>Notes
                <textarea value={appointmentNotes} onChange={(e) => setAppointmentNotes(e.target.value)} />
              </label>
              <button type="submit" className="analyze-button">Schedule appointment</button>
              {appointmentMessage && <p>{appointmentMessage}</p>}
              <h4>Recent appointments</h4>
              {localAppointments.slice(0, 12).map((item) => <div className="notification-item" key={item.id}>
                <p><strong>{item.patient_name}</strong> · {formatAppointmentTime(item)}</p>
                <p>{item.appointment_type} · {item.status}</p>
                {item.status === "SCHEDULED" && <>
                  {item.hospital_id ? <span>Awaiting hospital attendance record</span> : <button type="button" className="analyze-button" onClick={() => handleAttendLocalAppointment(item.id)}>Mark attended</button>}
                  <button type="button" className="analyze-button" onClick={() => { setRescheduleId(item.id); setRescheduleWhen(item.appointment_datetime.slice(0, 16)); }}>Reschedule</button>
                  <button type="button" className="analyze-button" onClick={() => handleCancelAppointment(item.id)}>Cancel appointment</button>
                  {rescheduleId === item.id && <form onSubmit={(event) => handleRescheduleAppointment(event, item.id)}>
                    <input type="datetime-local" value={rescheduleWhen} onChange={(event) => setRescheduleWhen(event.target.value)} required />
                    <button type="submit" className="analyze-button">Save new time</button>
                  </form>}
                </>}
              </div>)}
            </form>}

          </section>

          {/* ==================================================
              FOLLOW-UPS
          ================================================== */}

          {showFollowUps && (

            <section
              id="follow-ups-section"
              className="results-card"
            >

              <h3>
                📅 Patient Follow-ups
              </h3>

              <p>
                These patients currently have scheduled
                appointments.
              </p>

              {followUpError && (
                <p className="error-message">
                  {followUpError}
                </p>
              )}

              {followUpMessage && (
                <p className="success-message">
                  {followUpMessage}
                </p>
              )}

              {followUps.length === 0 &&
                !followUpError && (

                  <div className="info-card">

                    <h4>
                      No Scheduled Follow-ups
                    </h4>

                    <p>
                      There are currently no patients
                      with scheduled appointments.
                    </p>

                  </div>
                )}

              {followUps.map((item) => {

                const appointment =
                  item.appointment;

                return (
                  <div
                    key={
                      appointment?.id ||
                      item.screening_id
                    }
                    className="info-card"
                  >

                    <h4>
                      {item.patient_name}
                    </h4>

                    <p>
                      <strong>
                        Patient Code:
                      </strong>{" "}
                      {item.patient_code}
                    </p>

                    <p>
                      <strong>
                        Age:
                      </strong>{" "}
                      {item.age}
                    </p>

                    <p>
                      <strong>
                        Sex:
                      </strong>{" "}
                      {item.sex}
                    </p>

                    <p>
                      <strong>
                        Health Centre:
                      </strong>{" "}
                      {item.health_centre}
                    </p>

                    <p>
                      <strong>
                        Doctor:
                      </strong>{" "}
                      {appointment?.doctor_name ||
                        item.consulted_doctor ||
                        "-"}
                    </p>

                    <p>
                      <strong>
                        Appointment:
                      </strong>{" "}

                      {formatAppointmentTime(appointment)}
                    </p>

                    <p>
                      <strong>
                        Status:
                      </strong>{" "}

                      <span
                        style={{
                          fontWeight: "bold",
                        }}
                      >
                        {appointment?.status ||
                          "SCHEDULED"}
                      </span>
                    </p>

                    {appointment?.status ===
                      "SCHEDULED" && (

                      <div
                        style={{
                          display: "flex",
                          gap: "10px",
                          flexWrap: "wrap",
                          marginTop: "15px",
                        }}
                      >

                        <button
                          type="button"
                          className="analyze-button"
                          onClick={() =>
                            handleMarkAppointmentAttended(
                              appointment.id
                            )
                          }
                        >
                          ✓ Mark Attended
                        </button>

                      </div>
                    )}

                  </div>
                );
              })}

            </section>
          )}

          {/* ==================================================
              CASE ERROR
          ================================================== */}

          {hospitalCasesError && (
            <p className="error-message">
              {hospitalCasesError}
            </p>
          )}

          {/* ==================================================
              HOSPITAL CASE LIST
          ================================================== */}

          {hospitalView && (

            <section
              id="hospital-cases-section"
              className="results-card"
            >

              <h3>
                {hospitalView === "submitted"
                  ? "📋 Submitted Cases — Awaiting Doctor"
                  : "🩺 Patient Reviews — Attended Patients"}
              </h3>

              {hospitalView === "submitted" && (
                <p>
                  These patients have been referred to
                  the hospital but have not yet been
                  attended by a doctor.
                </p>
              )}

              {hospitalView === "reviewed" && (
                <p>
                  These patients have already been
                  attended by a doctor.
                </p>
              )}

              {hospitalCases.length === 0 &&
                !hospitalCasesError &&
                !isLoadingCases && (

                  <div className="info-card">

                    <h4>
                      No Patients Found
                    </h4>

                    <p>
                      {hospitalView === "submitted"
                        ? "There are currently no unattended submitted cases."
                        : "There are currently no attended patient reviews."}
                    </p>

                  </div>
                )}

              {hospitalCases.map((caseItem) => (

                <div
                  key={caseItem.screening_id}
                  className="info-card"
                >

                  <h4>
                    {caseItem.patient_name}
                  </h4>

                  <p>
                    <strong>
                      Patient Code:
                    </strong>{" "}
                    {caseItem.patient_code}
                  </p>

                  <p>
                    <strong>
                      Age:
                    </strong>{" "}
                    {caseItem.age}
                  </p>

                  <p>
                    <strong>
                      Sex:
                    </strong>{" "}
                    {caseItem.sex}
                  </p>

                  <p>
                    <strong>
                      Health Centre:
                    </strong>{" "}
                    {caseItem.health_centre}
                  </p>

                  <p>
                    <strong>
                      AI Prediction:
                    </strong>{" "}
                    {caseItem.prediction}
                  </p>

                  <p>
                    <strong>
                      Confidence:
                    </strong>{" "}
                    {Number(
                      caseItem.confidence
                    ).toFixed(2)}
                    %
                  </p>

                  <p>
                    <strong>
                      Screening Status:
                    </strong>{" "}
                    {caseItem.status}
                  </p>

                  {caseItem.appointment && (
                    <>

                      <p>
                        <strong>
                          Doctor:
                        </strong>{" "}
                        {caseItem.appointment
                          .doctor_name ||
                          "-"}
                      </p>

                      <p>
                        <strong>
                          Appointment Status:
                        </strong>{" "}
                        {caseItem.appointment
                          .status ||
                          "-"}
                      </p>

                      <p>
                        <strong>
                          Appointment:
                        </strong>{" "}

                        {formatAppointmentTime(caseItem.appointment)}
                      </p>

                    </>
                  )}

                  <button
                    type="button"
                    className="analyze-button"
                    onClick={() =>
                      handleViewCaseDetails(
                        caseItem
                      )
                    }
                  >
                    View Details
                  </button>

                </div>
              ))}

            </section>
          )}

          {/* ==================================================
              SELECTED CASE
          ================================================== */}

          {selectedCase && (

            <section
              id="case-details"
              className="results-card"
            >

              <h3>
                🔍 Selected Patient — Case Details
              </h3>

              <div className="info-card">

                <h4>
                  Patient Information
                </h4>

                <p>
                  <strong>
                    Patient Code:
                  </strong>{" "}
                  {selectedCase.patient_code}
                </p>

                <p>
                  <strong>
                    Name:
                  </strong>{" "}
                  {selectedCase.patient_name}
                </p>

                <p>
                  <strong>
                    Age:
                  </strong>{" "}
                  {selectedCase.age}
                </p>

                <p>
                  <strong>
                    Sex:
                  </strong>{" "}
                  {selectedCase.sex}
                </p>

                <p>
                  <strong>
                    Health Centre:
                  </strong>{" "}
                  {selectedCase.health_centre}
                </p>

              </div>

              <div className="info-card">

                <h4>
                  AI Screening Result
                </h4>

                <p>
                  <strong>
                    Prediction:
                  </strong>{" "}
                  {selectedCase.prediction}
                </p>

                <p>
                  <strong>
                    Confidence:
                  </strong>{" "}
                  {Number(
                    selectedCase.confidence
                  ).toFixed(2)}
                  %
                </p>

                <p>
                  <strong>
                    Screening Status:
                  </strong>{" "}
                  {selectedCase.status}
                </p>

              </div>

              {selectedCase.probabilities && (

                <div className="info-card">

                  <h4>
                    Class Probabilities
                  </h4>

                  <ul>

                    {Object.entries(
                      selectedCase.probabilities
                    ).map(
                      ([className, probability]) => (

                        <li key={className}>

                          <span>
                            {className}
                          </span>

                          <span>
                            {Number(
                              probability
                            ).toFixed(2)}
                            %
                          </span>

                        </li>
                      )
                    )}

                  </ul>

                </div>
              )}

              {selectedCase.gradcam_image_path && (

                <div className="info-card">

                  <h4>
                    Grad-CAM Explanation
                  </h4>

                  <p>
                    The highlighted regions show
                    areas that influenced the model's
                    prediction.
                  </p>

                  <AuthenticatedImage src={selectedCase.gradcam_image_path} token={user?.session_token} alt="Grad-CAM explanation" className="heatmap-image" />

                </div>
              )}

              {/* ==================================================
                  HOSPITAL CONSULTATION
              ================================================== */}

              <div className="info-card">

                <h4>
                  Hospital Consultation
                </h4>

                <div>

                  <label>
                    Consulted Doctor
                  </label>

                  <input
                    type="text"
                    value={consultedDoctor}
                    onChange={(e) =>
                      setConsultedDoctor(
                        e.target.value
                      )
                    }
                    placeholder="Enter doctor's name"
                  />

                </div>

                <div>

                  <label>
                    Doctor Notes
                  </label>

                  <textarea
                    value={doctorNotes}
                    onChange={(e) =>
                      setDoctorNotes(
                        e.target.value
                      )
                    }
                    placeholder="Enter consultation notes"
                    rows="5"
                  />

                </div>

                <div>

                  <label>
                    Next Appointment Date
                  </label>

                  <input
                    type="date"
                    value={appointmentDate}
                    min={
                      new Date()
                        .toISOString()
                        .split("T")[0]
                    }
                    onChange={(e) =>
                      setAppointmentDate(
                        e.target.value
                      )
                    }
                  />

                </div>

                <div>

                  <label>
                    Next Appointment Time
                  </label>

                  <input
                    type="time"
                    value={appointmentTime}
                    onChange={(e) =>
                      setAppointmentTime(
                        e.target.value
                      )
                    }
                  />

                </div>

                <div
                  style={{
                    marginTop: "15px",
                    padding: "14px",
                    background: "#eff6ff",
                    border:
                      "1px solid #bfdbfe",
                    borderRadius: "8px",
                  }}
                >

                  <strong>
                    📅 Next Hospital Appointment
                  </strong>

                  <p>
                    Set the date and time for the
                    patient's next hospital visit.
                  </p>

                </div>

                {appointmentDate &&
                  appointmentTime && (

                    <div
                      style={{
                        padding: "12px",
                        marginBottom: "15px",
                        background: "#f0fdf4",
                        border:
                          "1px solid #bbf7d0",
                        borderRadius: "8px",
                      }}
                    >

                      <strong>
                        Scheduled for:
                      </strong>{" "}

                      {new Date(
                        `${appointmentDate}T${appointmentTime}`
                      ).toLocaleString(
                        "en-IN",
                        {
                          dateStyle: "medium",
                          timeStyle: "short",
                        }
                      )}

                    </div>
                  )}

                {reviewError && (
                  <p className="error-message">
                    {reviewError}
                  </p>
                )}

                {reviewMessage && (
                  <p className="success-message">
                    {reviewMessage}
                  </p>
                )}

                <button
                  type="button"
                  className="analyze-button"
                  onClick={
                    handleSaveDoctorReview
                  }
                  disabled={isSavingReview}
                >
                  {isSavingReview
                    ? "Saving Consultation..."
                    : "Save Consultation & Schedule Appointment"}
                </button>

              </div>

              {/* ==================================================
                  EXISTING APPOINTMENT
              ================================================== */}

              {selectedCase.appointment && (

                <div className="info-card">

                  <h4>
                    📅 Scheduled Appointment
                  </h4>

                  <p>
                    <strong>
                      Doctor:
                    </strong>{" "}
                    {
                      selectedCase.appointment
                        .doctor_name
                    }
                  </p>

                  <p>
                    <strong>
                      Date & Time:
                    </strong>{" "}

                    {formatAppointmentTime(selectedCase.appointment)}
                  </p>

                  <p>
                    <strong>
                      Type:
                    </strong>{" "}
                    {
                      selectedCase.appointment
                        .appointment_type
                    }
                  </p>


                  <p>
                    <strong>
                      Status:
                    </strong>{" "}
                    {
                      selectedCase.appointment
                        .status
                    }
                  </p>

                </div>
              )}

              <button
                type="button"
                className="analyze-button"
                onClick={
                  handleCloseCaseDetails
                }
              >
                Close Details
              </button>

            </section>
          )}

        </main>

        <footer className="footer">

          <p>
            GlucoVision • Main Hospital
          </p>

          <p className="disclaimer">
            AI-assisted screening support only.
            Clinical decisions should be made by
            qualified healthcare professionals.
          </p>

        </footer>

      </div>
    );
  }

  // ============================================================
  // HEALTH CENTRE DASHBOARD
  // ============================================================

  const healthCentreReports = (patientId) => centreScreenings
    .filter((report) => String(report.patient_id) === String(patientId))
    .sort((left, right) => new Date(right.screening_date || 0) - new Date(left.screening_date || 0));
  const filteredCentrePatients = registeredPatients.filter((record) =>
    !centrePatientSearch.trim() || `${record.name || ""} ${record.patient_code || ""}`.toLowerCase().includes(centrePatientSearch.trim().toLowerCase()));
  const centreMissedAlerts = notifications.filter((notification) =>
    ["MISSED_APPOINTMENT", "REFERRAL_NON_ATTENDANCE"].includes(notification.notification_type));
  const activeCentreReport = centreScreenings.find((report) => String(report.screening_id) === String(expandedCentreReport)) || null;

  return (
    <div className="app">

      <header className="header">

        <div className="logo">

          <div className="logo-icon">
            G
          </div>

          <div>
            <h1>
              GlucoVision
            </h1>

            <p>
              Health Centre
            </p>
          </div>

        </div>

        <button onClick={handleLogout}>
          Logout
        </button>

      </header>

      <main className="main-content">

        <section className="hero">

          <h2>
            Health Centre Screening
          </h2>

          <p>
            Welcome, {user.name}. Register a patient or select an existing record, then continue to screening and report review.
          </p>

        </section>

        <nav className="health-centre-tabs" role="tablist" aria-label="Health centre dashboard">
          {[{ id: "register", label: "Register Patient & Screen" }, { id: "patients", label: "Registered Patients" }, { id: "missed", label: "Missed Appointments", count: centreMissedAlerts.length }].map((tab) => <button type="button" role="tab" aria-selected={activeCentreTab === tab.id} className={activeCentreTab === tab.id ? "active" : ""} key={tab.id} onClick={() => setActiveCentreTab(tab.id)}>{tab.label}{tab.count > 0 && <span className="tab-count">{tab.count}</span>}</button>)}
        </nav>

        {activeCentreTab === "patients" && <section className="results-card health-centre-tab-panel">
          <div className="centre-panel-heading"><div><h3>Registered Patients</h3><p>Search patients and review each screening in their history.</p></div><span>{filteredCentrePatients.length} patients</span></div>
          {centreRecordsLoading && <p className="loading-message" role="status">Loading patients and screening history…</p>}
          {centreScreeningsError && <p className="error-message" role="alert">{centreScreeningsError}</p>}
          <label className="centre-search-label">Search by patient name or ID<input type="search" value={centrePatientSearch} onChange={(event) => setCentrePatientSearch(event.target.value)} placeholder="Patient name or ID" /></label>
          {!centreRecordsLoading && !centreScreeningsError && filteredCentrePatients.length === 0 && <p className="empty-state">{registeredPatients.length ? "No patients match your search." : "No patients are registered with this health centre yet."}</p>}
          <div className="registered-patient-list">{filteredCentrePatients.map((record) => {
            const patientReports = healthCentreReports(record.id);
            const latest = patientReports[0];
            return <article className="registered-patient-card" key={record.id}>
              <div className="registered-patient-summary"><div><h4>{record.name}</h4><p>Patient ID {record.patient_code || record.id} · {record.age ?? "Age not recorded"} · {record.sex || "Sex not recorded"}{record.phone ? ` · ${record.phone}` : ""}</p></div><div className="latest-screening-summary">{latest ? <><strong>{latest.prediction || "Finding not recorded"}</strong><span>{latest.confidence ? `${latest.confidence}% confidence` : "Confidence not recorded"} · {latest.screening_date ? new Date(latest.screening_date).toLocaleDateString() : "Date unavailable"}</span></> : <span>Not screened yet</span>}</div></div>
              {latest && <div className="registered-patient-status"><span>Referral: {latest.submitted_to_hospital === "YES" ? "Submitted" : latest.referral_status || "Not submitted"}{latest.hospital_name ? ` · ${latest.hospital_name}` : ""}</span><span>Hospital review: {latest.review_status || "Not recorded"}</span><span>Attendance: {latest.hospital_attended_at ? "Attended" : latest.appointment?.status === "MISSED" ? "Missed appointment" : "Not recorded"}</span><span>Next appointment: {latest.appointment?.appointment_datetime ? `${formatAppointmentTime(latest.appointment)} · ${latest.appointment.status}` : "Not scheduled"}</span></div>}
              <div className="registered-patient-actions"><button type="button" onClick={() => setExpandedPatientHistory(expandedPatientHistory === record.id ? null : record.id)}>{expandedPatientHistory === record.id ? "Hide Patient History" : "View Patient History"}</button><button type="button" className="primary-action" onClick={() => startScreeningForPatient(record)}>Screen Patient</button></div>
              {expandedPatientHistory === record.id && <div className="patient-history-list">{patientReports.length === 0 ? <p className="empty-state">No screening history is available for this patient.</p> : patientReports.map((report) => <article className="patient-history-row" key={report.screening_id}><div><strong>Report #{report.screening_id} · {report.prediction || "Finding not recorded"}</strong><span>{report.screening_date ? new Date(report.screening_date).toLocaleString() : "Date unavailable"} · Confidence {report.confidence || "Not recorded"}</span><span>Referral: {report.submitted_to_hospital === "YES" ? "Submitted" : "Not submitted"} · Review: {report.review_status || "Not recorded"}</span></div><div className="patient-history-actions"><button type="button" onClick={() => setExpandedCentreReport(report.screening_id)}>View Complete Report</button>{report.original_report_pdf_available ? <button type="button" disabled={openingCentrePdf === report.screening_id} onClick={() => openSavedCentrePdf(report.screening_id)}>{openingCentrePdf === report.screening_id ? "Opening PDF…" : "View Original Screening PDF"}</button> : <span className="muted-message">Original PDF unavailable for this legacy report.</span>}<button type="button" onClick={() => startScreeningForPatient(record)}>Screen Patient</button></div></article>)}</div>}
            </article>;
          })}</div>
        </section>}

        {activeCentreTab === "missed" && <section className="results-card health-centre-tab-panel">
          <div className="centre-panel-heading"><div><h3>Missed Appointments</h3><p>Scheduled consultation misses and referral non-attendance alerts are listed as separate events.</p></div><span>{centreMissedAlerts.length} alerts</span></div>
          {notificationsLoading && <p className="loading-message" role="status">Loading appointment and referral alerts…</p>}
          {notificationsError && <p className="error-message" role="alert">{notificationsError}</p>}
          {!notificationsLoading && !notificationsError && centreMissedAlerts.length === 0 && <p className="empty-state">No missed appointments or pending hospital non-attendance alerts.</p>}
          <div className="missed-alert-list">{centreMissedAlerts.map((notification) => <article className="missed-alert-card" key={notification.id}>
            <div className="missed-alert-heading"><strong>{notification.notification_type === "REFERRAL_NON_ATTENDANCE" ? "Referral non-attendance · five-calendar-day alert" : "Missed scheduled consultation"}</strong><span className={`status-pill ${notification.resolved_at ? "resolved" : "pending"}`}>{notification.resolved_at ? "Resolved" : notification.is_read ? "Acknowledged · Follow-up required" : "Unread · Follow-up required"}</span></div>
            <div className="missed-alert-details"><span><strong>Patient</strong>{notification.patient_name} · {notification.patient_code || notification.patient_id}</span>{notification.referral_screening_id && <span><strong>Report ID</strong>#{notification.referral_screening_id}</span>}{notification.appointment_id && <span><strong>Report ID</strong>#{notification.report_id || "—"}</span>}{notification.patient_phone && <span><strong>Phone</strong>{notification.patient_phone}</span>}<span><strong>Originating health centre</strong>{user.health_centre_name || "Your health centre"}</span><span><strong>Assigned hospital</strong>{notification.assigned_hospital || "Not recorded"}</span>{notification.doctor_name && <span><strong>Doctor</strong>{notification.doctor_name}</span>}{notification.appointment_datetime && <span><strong>Scheduled appointment</strong>{new Date(notification.appointment_datetime).toLocaleString()}</span>}{notification.missed_detected_at && <span><strong>Marked missed</strong>{new Date(notification.missed_detected_at).toLocaleString()}</span>}{notification.appointment_status && <span><strong>Appointment status</strong>{notification.appointment_status}</span>}{notification.referral_submitted_at && <span><strong>Referral submitted</strong>{new Date(notification.referral_submitted_at).toLocaleString()}</span>}{notification.referral_deadline_at && <span><strong>Five-calendar-day deadline</strong>{new Date(notification.referral_deadline_at).toLocaleString()}</span>}<span><strong>Notification date</strong>{notification.created_at ? new Date(notification.created_at).toLocaleString() : "Not recorded"}</span></div>
            <p>{notification.message}</p>{notification.resolved_at && <p>Resolved {new Date(notification.resolved_at).toLocaleString()}</p>}
            {!notification.is_read && <button type="button" className="secondary-action" onClick={() => handleNotificationRead(notification.id)}>Mark as acknowledged</button>}
          </article>)}</div>
        </section>}

        {/* ==================================================
            PATIENT REGISTRATION
        ================================================== */}

        {activeCentreTab === "register" && <div className="health-centre-tab-panel registration-screening-workflow">
        <section className="upload-card patient-registration-panel">

          <h3>
            Step 1 · Register or select a patient
          </h3>

          <label className="existing-patient-picker">Select Existing Patient
            <input type="search" value={existingPatientSearch} onChange={(event) => setExistingPatientSearch(event.target.value)} placeholder="Search by patient name or ID" />
            <select value={patient?.id || ""} onChange={(event) => selectPatientForScreening(event.target.value)}>
              <option value="">Search or choose a registered patient</option>
              {registeredPatients.filter((item) => !existingPatientSearch.trim() || `${item.name || ""} ${item.patient_code || item.id}`.toLowerCase().includes(existingPatientSearch.trim().toLowerCase())).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.patient_code || item.id}</option>)}
            </select>
          </label>
          {registeredPatients.length === 0 && <p className="form-help">No patients are registered yet. Register a patient below to continue.</p>}
          <div className="registration-divider"><span>Or register a new patient</span></div>

          <form
            onSubmit={
              handlePatientRegistration
            }
          >

            <div>

              <label>
                Patient Name
              </label>

              <input
                type="text"
                value={patientName}
                onChange={(e) =>
                  setPatientName(
                    e.target.value
                  )
                }
                placeholder="Enter patient name"
                required
              />

            </div>

            <div>

              <label>
                Age
              </label>

              <input
                type="number"
                min="1"
                max="120"
                value={patientAge}
                onChange={(e) =>
                  setPatientAge(
                    e.target.value
                  )
                }
                placeholder="Enter age"
                required
              />

            </div>

            <div>

              <label>
                Sex
              </label>

              <select
                value={patientSex}
                onChange={(e) =>
                  setPatientSex(
                    e.target.value
                  )
                }
                required
              >

                <option value="">
                  Select sex
                </option>

                <option value="Male">
                  Male
                </option>

                <option value="Female">
                  Female
                </option>

                <option value="Other">
                  Other
                </option>

              </select>

            </div>

            <div>
              <label>Registered Phone (optional)</label>
              <input type="tel" value={patientPhone} onChange={(e) => setPatientPhone(e.target.value)} placeholder="Enter phone number" />
            </div>

            {patientError && (
              <p className="error-message">
                {patientError}
              </p>
            )}

            <button
              type="submit"
              className="analyze-button"
              disabled={isRegistering}
            >
              {isRegistering
                ? "Registering..."
                : "Register Patient"}
            </button>

          </form>

          {patientRegisteredMessage && <p className="success-message" role="status">{patientRegisteredMessage}</p>}
          {patient && <p className="selected-patient-summary">Selected patient: <strong>{patient.name}</strong> · ID {patient.patient_code || patient.id}</p>}

        </section>

        {/* ==================================================
            RETINAL IMAGE
        ================================================== */}

        {patient && <section className="upload-card screening-upload-section">

          <h3>
            Step 2 · Upload retinal image
          </h3>

          {patient && (
            <p>
              Screening patient:{" "}
              <strong>
                {patient.patient_code ||
                  `PAT-${patient.patient_id || patient.id}`}{" "}
                -{" "}
                {patient.name}
              </strong>
            </p>
          )}

          <label className="upload-area">

            {selectedImage ? (

              <img
                src={selectedImage}
                alt="Selected retinal image"
                className="preview-image"
              />

            ) : (

              <>
                <div className="upload-icon">
                  ↑
                </div>

                <h4>
                  Choose a retinal image
                </h4>

                <p>
                  PNG, JPG or JPEG
                </p>
              </>
            )}

            <input
              type="file"
              accept="image/png,image/jpeg,image/jpg"
              onChange={handleImageChange}
              hidden
              disabled={!patient}
            />

          </label>

          {selectedImage && (

            <button
              type="button"
              className="analyze-button"
              onClick={handleAnalyze}
              disabled={
                isLoading || !patient
              }
            >
              {isLoading
                ? "Analyzing..."
                : "Analyze Image"}
            </button>
          )}

          {error && (
            <p className="error-message">
              {error}
            </p>
          )}

          {/* ==================================================
              RESULT
          ================================================== */}

          {result && <section className="analysis-result-summary" aria-live="polite">
            <div><span className="eyebrow">Analysis complete · Report #{result.screening_id}</span><h4>{result.prediction}</h4><p>Confidence <strong>{Number(result.confidence).toFixed(2)}%</strong> · Patient {patient?.name} · {patient?.patient_code || patient?.id}</p></div>
            <div className="analysis-result-actions"><button type="button" onClick={() => setExpandedCentreReport(result.screening_id)}>View Complete Report</button><button type="button" onClick={handlePrintReport}>View Original Screening PDF</button>{!isNoDR(result.prediction) && result.status !== "SUBMITTED" && result.submitted_to_hospital !== "YES" && <button type="button" className="primary-action" onClick={handleSubmitToHospital} disabled={isSubmitting}>{isSubmitting ? "Submitting referral…" : "Submit to Hospital"}</button>}</div>
            {isNoDR(result.prediction) && <p className="success-message">Hospital referral is not required for this screening result.</p>}{(result.status === "SUBMITTED" || result.submitted_to_hospital === "YES") && <p className="success-message">Screening submitted to the hospital.</p>}{submissionMessage && <p className="success-message">{submissionMessage}</p>}
          </section>}

        </section>}
        {!patient && <p className="screening-next-step">Register a patient or select an existing patient above to continue to retinal image upload.</p>}
        </div>}

        {activeCentreReport && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setExpandedCentreReport(null); }}>
          <section className="dashboard-modal report-modal" role="dialog" aria-modal="true" aria-labelledby="centre-report-title">
            <header className="modal-header"><div><span className="eyebrow">Original screening report · Report #{activeCentreReport.screening_id}</span><h2 id="centre-report-title">{activeCentreReport.patient_name} · {activeCentreReport.patient_code}</h2></div><button type="button" className="modal-close" onClick={() => setExpandedCentreReport(null)}>Close</button></header>
            <div className="modal-body">
              <section className="report-section"><h3>Screening summary</h3><p><strong>Screened:</strong> {activeCentreReport.screening_date ? new Date(activeCentreReport.screening_date).toLocaleString() : "Date unavailable"}</p><p><strong>AI predicted severity:</strong> {activeCentreReport.prediction || "Not recorded"} · <strong>Confidence:</strong> {activeCentreReport.confidence || "Not recorded"}%</p><p><strong>Referral:</strong> {activeCentreReport.submitted_to_hospital === "YES" ? `Submitted ${activeCentreReport.submitted_at ? new Date(activeCentreReport.submitted_at).toLocaleString() : ""}` : "Not submitted"} · <strong>Assigned hospital:</strong> {activeCentreReport.hospital_name || "Not assigned"}</p><p><strong>Hospital review:</strong> {activeCentreReport.review_status || "Not recorded"} · <strong>Attendance:</strong> {activeCentreReport.hospital_attended_at ? new Date(activeCentreReport.hospital_attended_at).toLocaleString() : "Not recorded"}</p><p><strong>Clinical disposition:</strong> {activeCentreReport.clinical_disposition?.replaceAll("_", " ") || "Not recorded"}{activeCentreReport.clinical_outcome ? ` · ${activeCentreReport.clinical_outcome.replaceAll("_", " ")}` : ""}</p><p><strong>Next appointment:</strong> {activeCentreReport.appointment?.appointment_datetime ? `${formatAppointmentTime(activeCentreReport.appointment)} · ${activeCentreReport.appointment.status} · Dr. ${activeCentreReport.appointment.doctor_name || "Not recorded"}` : "Not scheduled"}</p></section>
              <section className="report-section"><h3>Stored classification scores</h3>{Object.keys(activeCentreReport.probabilities || {}).length ? <div className="score-table-wrap"><table><thead><tr><th>Class</th><th>Score</th></tr></thead><tbody>{Object.entries(activeCentreReport.probabilities).map(([name, score]) => <tr key={name}><td>{name}</td><td>{typeof score === "number" ? `${score.toFixed(2)}%` : score}</td></tr>)}</tbody></table></div> : <p>No classification scores are available for this report.</p>}</section>
              <section className="report-section"><h3>Retinal images</h3>{activeCentreReport.original_image_url ? <figure><figcaption>Original retinal image</figcaption><AuthenticatedImage src={activeCentreReport.original_image_url} token={user.session_token} alt={`Retinal image for screening ${activeCentreReport.screening_id}`} className="report-image" /></figure> : <p>Original image is unavailable for this report.</p>}{activeCentreReport.gradcam_image_path ? <figure><figcaption>Grad-CAM explanation</figcaption><AuthenticatedImage src={activeCentreReport.gradcam_image_path} token={user.session_token} alt={`Grad-CAM explanation for screening ${activeCentreReport.screening_id}`} className="report-image" /></figure> : <p>Grad-CAM explanation is unavailable for this report.</p>}</section>
              <section className="report-section"><h3>Hospital clinical review</h3><p><strong>Doctor:</strong> {activeCentreReport.doctor_name || "Not recorded"}</p><p><strong>Assessment:</strong> {activeCentreReport.clinical_review_notes || "Not recorded"}</p><p><strong>Recommendations:</strong> {activeCentreReport.doctor_notes || "Not recorded"}</p><p><strong>Follow-up priority:</strong> {activeCentreReport.follow_up_priority || "Not recorded"}</p></section>
              <div className="report-modal-actions">{activeCentreReport.original_report_pdf_available ? <button type="button" onClick={() => openSavedCentrePdf(activeCentreReport.screening_id)}>View Original Screening PDF</button> : <p className="muted-message">The original PDF is unavailable for this legacy report.</p>}<button type="button" onClick={() => { startScreeningForPatient(registeredPatients.find((item) => item.id === activeCentreReport.patient_id) || patient); setExpandedCentreReport(null); }}>Screen Patient Again</button></div>
            </div>
          </section>
        </div>}

      </main>

      <footer className="footer">

        <p>
          GlucoVision • AI-assisted screening prototype
        </p>

        <p className="disclaimer">
          This tool is intended for screening support
          and research purposes only. It is not a
          medical diagnosis and should not replace
          evaluation by a qualified healthcare
          professional.
        </p>

      </footer>

    </div>
  );
}

export default App;
