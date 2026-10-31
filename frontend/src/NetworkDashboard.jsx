import { useCallback, useEffect, useState } from "react";
import AuthenticatedImage from "./AuthenticatedImage";

const blankHospital = { name: "", code: "", district: "", state: "", address: "", contact_number: "", official_email: "", is_active: true };
const blankCentre = { name: "", code: "", district: "", state: "", address: "", contact_number: "", assigned_hospital_id: "", is_active: true };
const localDateTimeInput = (value) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};
const formatPercent = (value) => {
  if (value === null || value === undefined || value === "") return "Not recorded";
  const numeric = Number(String(value).replace("%", ""));
  return Number.isFinite(numeric) ? `${numeric.toFixed(2)}%` : String(value);
};
const cleanLabel = (value) => typeof value === "string" ? value.trim() : value;
const dispositionLabels = { FOLLOW_UP_REQUIRED: "Follow-up Required", STABLE_MONITORING: "Stable — Monitoring", DISCHARGED_CARE_COMPLETED: "Completed / Discharged" };
const outcomeLabels = { RECOVERED: "Recovered as documented", DISCHARGED_WITHOUT_DOCUMENTED_RECOVERY: "Discharged without documented recovery" };
const dispositionLabel = (value) => dispositionLabels[value] || "Disposition not recorded";
const followUpStatus = (report) => report.follow_up_required === true ? "Further monitoring / review required" : report.follow_up_required === false ? "No further monitoring documented" : "Not documented";
const hasNextAppointment = (report) => report?.appointment?.status === "SCHEDULED" && new Date(report.appointment.appointment_datetime) > new Date();
const needsNextAppointment = (report) => ["FOLLOW_UP_REQUIRED", "STABLE_MONITORING"].includes(report?.clinical_disposition) && !hasNextAppointment(report);

export default function NetworkDashboard({ user, onLogout }) {
  const [overview, setOverview] = useState(null);
  const [hospitals, setHospitals] = useState([]);
  const [centres, setCentres] = useState([]);
  const [districts, setDistricts] = useState([]);
  const [network, setNetwork] = useState(null);
  const [hospitalLoading, setHospitalLoading] = useState(true);
  const [hospitalForm, setHospitalForm] = useState(blankHospital);
  const [centreForm, setCentreForm] = useState(blankCentre);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const [hospitalFilter, setHospitalFilter] = useState("");
  const [accountDialog, setAccountDialog] = useState(null);
  const [accountForm, setAccountForm] = useState({ username: "", name: "", password: "" });
  const [reportFilter, setReportFilter] = useState({ centre: "", status: "", risk: "", date: "" });
  const [patientSearch, setPatientSearch] = useState("");
  const [activePatientTab, setActivePatientTab] = useState("new");
  const [activeReportId, setActiveReportId] = useState(null);
  const [reviewDraft, setReviewDraft] = useState(null);
  const [appointmentDraft, setAppointmentDraft] = useState(null);
  const [followUpDraft, setFollowUpDraft] = useState(null);
  const [savingReportId, setSavingReportId] = useState(null);
  const [reviewError, setReviewError] = useState("");
  const [appointmentError, setAppointmentError] = useState("");
  const [followUpError, setFollowUpError] = useState("");
  const activeReport = network?.reports?.find((report) => report.id === activeReportId) || null;
  const request = useCallback(async (url, options = {}) => {
    const response = await fetch(`/api${url}`, { ...options, headers: { Authorization: `Bearer ${user.session_token}`, ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers } });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Request failed");
    return data;
  }, [user.session_token]);
  const openOriginalPdf = async (screeningId) => {
    const opened = window.open("about:blank", "_blank");
    try {
      const response = await fetch(`/api/screening/${screeningId}/original-pdf`, { headers: { Authorization: `Bearer ${user.session_token}` } });
      if (!response.ok) throw new Error("Unable to open the original screening PDF.");
      const objectUrl = URL.createObjectURL(await response.blob());
      if (opened) opened.location = objectUrl;
      else { const link = document.createElement("a"); link.href = objectUrl; link.download = `GlucoVision-report-${screeningId}.pdf`; link.click(); }
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
    } catch (error) { if (opened) opened.close(); setError(error.message); }
  };
  const downloadOriginalPdf = async (screeningId) => {
    try {
      const response = await fetch(`/api/screening/${screeningId}/original-pdf`, { headers: { Authorization: `Bearer ${user.session_token}` } });
      if (!response.ok) throw new Error("The original screening PDF is unavailable.");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `GlucoVision_Screening_Report_${screeningId}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (downloadError) { setError(downloadError.message); }
  };
  const printOriginalPdf = async (screeningId) => {
    const printWindow = window.open("about:blank", "_blank");
    if (!printWindow) { setError("Allow pop-ups to print the report, or use Download Original Screening PDF."); return; }
    try {
      const response = await fetch(`/api/screening/${screeningId}/original-pdf`, { headers: { Authorization: `Bearer ${user.session_token}` } });
      if (!response.ok) throw new Error("The original screening PDF is unavailable.");
      const url = URL.createObjectURL(await response.blob());
      printWindow.location = url;
      window.setTimeout(() => { printWindow.focus(); printWindow.print(); }, 900);
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (printError) { printWindow.close(); setError(printError.message); }
  };
  const loadAdmin = useCallback(async () => {
    const [summary, hospitalRows, centreRows] = await Promise.all([request("/admin/overview"), request("/admin/hospitals"), request("/admin/health-centres")]);
    setOverview(summary); setHospitals(hospitalRows.hospitals); setCentres(centreRows.health_centres); setDistricts(centreRows.districts || []);
  }, [request]);
  const loadHospital = useCallback(async () => setNetwork(await request("/hospital/dashboard")), [request]);
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        if (user.role === "SUPER_ADMIN") {
          const [summary, hospitalRows, centreRows] = await Promise.all([request("/admin/overview"), request("/admin/hospitals"), request("/admin/health-centres")]);
          if (active) { setOverview(summary); setHospitals(hospitalRows.hospitals); setCentres(centreRows.health_centres); setDistricts(centreRows.districts || []); }
        } else {
          if (active) setHospitalLoading(true);
          const data = await request("/hospital/dashboard");
          if (active) setNetwork(data);
        }
      } catch (e) { if (active) setError(e.message); }
      finally { if (active && user.role !== "SUPER_ADMIN") setHospitalLoading(false); }
    };
    load();
    return () => { active = false; };
  }, [user.role, request]);

  const submit = async (url, payload, method = "POST") => {
    setMessage(""); setError("");
    try { await request(url, { method, body: JSON.stringify(payload) }); setMessage("Saved successfully."); await loadAdmin(); return true; }
    catch (e) { setError(e.message); return false; }
  };
  const openAccountDialog = (mode, type, organisation) => {
    setAccountDialog({ mode, type, organisation });
    setAccountForm({ username: "", name: organisation.name, password: "" });
  };
  const saveAccount = async (event) => {
    event.preventDefault();
    if (!accountDialog) return;
    const { mode, type, organisation } = accountDialog;
    const url = `/admin/accounts/${type}/${organisation.id}${mode === "reset" ? "/reset-password" : ""}`;
    const payload = mode === "reset" ? { password: accountForm.password } : accountForm;
    const saved = await submit(url, payload);
    if (!saved) return;
    setAccountForm({ username: "", name: "", password: "" });
    setAccountDialog(null);
  };
  const filteredCentres = centres.filter((c) => (!filter || (c.district || "").trim().toLocaleLowerCase() === filter.trim().toLocaleLowerCase()) && (!hospitalFilter || (hospitalFilter === "unassigned" ? c.assigned_hospital_id == null : String(c.assigned_hospital_id) === hospitalFilter)));
  const saveReview = async (event) => {
    event.preventDefault();
    if (!reviewDraft) return;
    if (!reviewDraft.clinical_disposition) {
      setReviewError("Choose a clinical disposition before saving this review.");
      return;
    }
    if (reviewDraft.clinical_disposition !== "DISCHARGED_CARE_COMPLETED") {
      if (!reviewDraft.notes.trim()) { setReviewError("Document the clinical assessment before saving this review."); return; }
      if (!reviewDraft.doctor_name.trim()) { setReviewError("Enter the reviewing doctor's name."); return; }
      if (!reviewDraft.appointment_datetime) { setReviewError("Choose the next appointment date and time."); return; }
      const appointmentTime = new Date(reviewDraft.appointment_datetime);
      if (Number.isNaN(appointmentTime.getTime()) || appointmentTime <= new Date()) { setReviewError("The next appointment must be a valid future date and time."); return; }
    } else if (!reviewDraft.notes.trim()) {
      setReviewError("Document the clinical basis for completing or discharging this care episode."); return;
    }
    if (reviewDraft.clinical_disposition === "STABLE_MONITORING" && !reviewDraft.follow_up_required) {
      setReviewError("Select further monitoring / review required, or choose Discharged / Care Completed if the hospital care episode has ended.");
      return;
    }
    if (reviewDraft.clinical_disposition === "STABLE_MONITORING" && !reviewDraft.recommendations.trim()) {
      setReviewError("Document the monitoring or review plan in Recommendations / next steps.");
      return;
    }
    if (reviewDraft.clinical_disposition === "DISCHARGED_CARE_COMPLETED" && !reviewDraft.clinical_outcome) {
      setReviewError("Choose the documented outcome for this completed care episode.");
      return;
    }
    setSavingReportId(reviewDraft.id); setError(""); setMessage(""); setReviewError("");
    try {
      await request(`/hospital/reports/${reviewDraft.id}/review`, { method: "POST", body: JSON.stringify({
        doctor_name: reviewDraft.doctor_name, notes: reviewDraft.notes,
        recommendations: reviewDraft.recommendations, flagged: reviewDraft.flagged,
        follow_up_priority: reviewDraft.follow_up_priority,
        clinical_disposition: reviewDraft.clinical_disposition,
        clinical_outcome: reviewDraft.clinical_outcome,
        follow_up_required: reviewDraft.follow_up_required,
        appointment_datetime: reviewDraft.appointment_datetime || null,
        appointment_type: "Hospital Consultation",
        appointment_notes: reviewDraft.appointment_notes || reviewDraft.recommendations,
      }) });
      setReviewDraft(null); setMessage("Clinical review saved; the AI prediction was preserved."); await loadHospital();
    } catch (e) { setReviewError(e.message); }
    finally { setSavingReportId(null); }
  };
  const saveAppointment = async (event) => {
    event.preventDefault();
    if (!appointmentDraft) return;
    setSavingReportId(appointmentDraft.id); setError(""); setMessage(""); setAppointmentError("");
    try {
      if (appointmentDraft.kind === "reschedule") {
        await request(`/hospital/appointments/${appointmentDraft.id}`, { method: "PATCH", body: JSON.stringify({
          appointment_datetime: appointmentDraft.appointment_datetime,
          doctor_name: appointmentDraft.doctor_name, notes: appointmentDraft.notes,
        }) });
      } else {
        await request(`/hospital/reports/${appointmentDraft.id}/appointments`, { method: "POST", body: JSON.stringify({
          appointment_datetime: appointmentDraft.appointment_datetime,
          doctor_name: appointmentDraft.doctor_name,
          appointment_type: "Hospital Consultation", notes: appointmentDraft.notes,
        }) });
      }
      setAppointmentDraft(null); setMessage(appointmentDraft.kind === "reschedule" ? "Appointment rescheduled." : "Consultation scheduled."); await loadHospital();
    } catch (e) { setAppointmentError(e.message); }
    finally { setSavingReportId(null); }
  };
  const updateAppointment = async (id, payload) => {
    setError(""); setMessage("");
    try { await request(`/hospital/appointments/${id}`, { method: "PATCH", body: JSON.stringify(payload) }); setMessage("Appointment updated."); await loadHospital(); return true; }
    catch (e) { setAppointmentError(e.message); setError(e.message); return false; }
  };
  const filteredReports = network?.reports?.filter((r) =>
    (!reportFilter.centre || String(r.health_centre_id) === reportFilter.centre) &&
    (!reportFilter.status || r.review_status === reportFilter.status) &&
    (!reportFilter.risk || (r.prediction || "").toLowerCase().includes(reportFilter.risk.toLowerCase())) &&
    (!reportFilter.date || (r.submitted_at && new Date(r.submitted_at).toLocaleDateString("en-CA") === reportFilter.date)) &&
    (!patientSearch.trim() || `${r.patient_name || ""} ${r.patient_code || ""} ${r.id}`.toLowerCase().includes(patientSearch.trim().toLowerCase()))) || [];
  const patientMap = new Map();
  for (const report of [...filteredReports].sort((a, b) => new Date(b.screening_date || 0) - new Date(a.screening_date || 0))) {
    if (!patientMap.has(report.patient_id)) patientMap.set(report.patient_id, { id: report.patient_id, name: report.patient_name, code: report.patient_code, reports: [] });
    patientMap.get(report.patient_id).reports.push(report);
  }
  const patientRows = [...patientMap.values()].map((patient) => {
    const latest = patient.reports[0];
    const category = latest.clinical_disposition === "DISCHARGED_CARE_COMPLETED" ? "completed"
      : ["FOLLOW_UP_REQUIRED", "STABLE_MONITORING"].includes(latest.clinical_disposition) ? "ongoing" : "new";
    return { ...patient, latest, category };
  });
  const missedAppointments = (network?.appointments || []).filter((a) => a.status === "MISSED" &&
    (!reportFilter.centre || String(a.health_centre_id) === reportFilter.centre) &&
    (!patientSearch.trim() || `${a.patient_name || ""} ${a.patient_code || ""} ${a.screening_id || ""}`.toLowerCase().includes(patientSearch.trim().toLowerCase())));
  const patientTabs = [
    { id: "new", label: "New Referrals", description: "Referrals awaiting an initial review or saved care decision.", rows: patientRows.filter((p) => p.category === "new") },
    { id: "ongoing", label: "Ongoing Care", description: "Patients with Follow-up Required or Stable — Monitoring documented.", rows: patientRows.filter((p) => p.category === "ongoing") },
    { id: "completed", label: "Completed", description: "Patients with explicit completion or discharge documentation.", rows: patientRows.filter((p) => p.category === "completed") },
    { id: "missed", label: "Missed Appointments", description: "Missed consultations with appointment history and follow-up actions.", rows: missedAppointments },
  ];
  const upcomingAppointments = (network?.appointments || []).filter((a) => a.status === "SCHEDULED" && new Date(a.appointment_datetime) > new Date());
  const otherFollowUps = (network?.notifications || []).filter((n) => !missedAppointments.some((a) => a.id === n.appointment_id));
  const startReview = (report) => {
    setReviewError("");
    setReviewDraft({ id: report.id, doctor_name: report.doctor_name || report.appointment?.doctor_name || user.name || "", notes: report.clinical_review_notes || "", recommendations: report.recommendations || "", flagged: Boolean(report.clinically_flagged), follow_up_required: Boolean(report.follow_up_required), follow_up_priority: report.follow_up_priority || "ROUTINE", clinical_disposition: report.clinical_disposition || "", clinical_outcome: report.clinical_outcome || "", appointment_datetime: report.appointment?.status === "SCHEDULED" ? localDateTimeInput(report.appointment.appointment_datetime) : "", appointment_notes: report.appointment?.notes || "", reviewed_at: report.clinical_reviewed_at || null });
  };
  const startAppointment = (report) => {
    const appointment = report.appointment;
    setAppointmentError("");
    if (["SCHEDULED", "MISSED"].includes(appointment?.status)) {
      setAppointmentDraft({ kind: "reschedule", id: appointment.id, reportId: report.id, doctor_name: appointment.doctor_name || "", appointment_datetime: appointment.status === "MISSED" ? "" : localDateTimeInput(appointment.appointment_datetime), notes: appointment.notes || "" });
    } else {
      setAppointmentDraft({ kind: "create", id: report.id, reportId: report.id, doctor_name: report.doctor_name || user.name || "", appointment_datetime: "", notes: "" });
    }
  };
  const renderPatient = (patient) => {
    const report = patient.latest;
    const referralStatus = report.submitted_to_hospital === "YES" ? "Referred" : "Not referred";
    const appointmentStatus = report.hospital_attended_at ? "Attended" : report.appointment?.status || "Not scheduled";
    return <article className="patient-category-card" key={patient.id}>
      <div className="patient-card-identity"><div><strong>{patient.name || "Patient name not recorded"}</strong><span>Patient ID {patient.code || patient.id} · Report #{report.id} · {cleanLabel(report.health_centre) || "Health centre not recorded"}</span></div><span className="screening-severity">{report.prediction || "Finding unavailable"}</span></div>
      <div className="patient-card-facts"><span><strong>Referral</strong>{referralStatus}</span><span><strong>Clinical disposition</strong>{dispositionLabel(report.clinical_disposition)}</span><span><strong>Next appointment</strong>{hasNextAppointment(report) ? new Date(report.appointment.appointment_datetime).toLocaleString() : needsNextAppointment(report) ? "Appointment required" : "None scheduled"}</span><span><strong>Doctor / status</strong>{report.appointment?.doctor_name || report.doctor_name || "Not recorded"} · {appointmentStatus}</span></div>
      <div className="patient-card-actions"><button type="button" onClick={() => setActiveReportId(report.id)}>View Report</button><button type="button" onClick={() => startReview(report)}>Clinical Review</button><button type="button" onClick={() => startAppointment(report)}>Appointment</button></div>
    </article>;
  };
  const renderMissedAppointment = (appointment) => {
    const note = network.notifications.find((notification) => notification.appointment_id === appointment.id);
    const next = network.appointments.find((candidate) => candidate.screening_id === appointment.screening_id && candidate.status === "SCHEDULED");
    return <article className="missed-appointment-row" key={appointment.id}>
      <div><strong>{appointment.patient_name || "Patient name not recorded"} · Patient ID {appointment.patient_code || appointment.patient_id}</strong><span>Report #{appointment.screening_id || "—"} · {appointment.health_centre || "Health centre not recorded"}</span><span>Missed {appointment.appointment_datetime ? new Date(appointment.appointment_datetime).toLocaleString() : "date unavailable"} · Dr. {appointment.doctor_name || "Not recorded"} · Status: {appointment.status}</span>{next && <span>Next appointment: {new Date(next.appointment_datetime).toLocaleString()} · Dr. {next.doctor_name}</span>}<span>{note?.resolved_at ? "Attendance recorded; notification resolved" : note?.follow_up_at ? `Health-centre follow-up: ${note.follow_up}` : "Health centre notified; follow-up required"}</span></div>
      <div className="missed-appointment-actions">{note && <button type="button" onClick={() => followUp(note)}>{note.follow_up_at ? "Update Health-centre Follow-up" : "Record Health-centre Follow-up"}</button>}<button type="button" onClick={() => setAppointmentDraft({ kind: "reschedule", id: appointment.id, reportId: appointment.screening_id, doctor_name: appointment.doctor_name || user.name || "", appointment_datetime: "", notes: appointment.notes || "" })}>{next ? "Reschedule Consultation" : "Schedule Consultation"}</button><button type="button" onClick={() => updateAppointment(appointment.id, { status: "ATTENDED" })}>Record Late Attendance</button></div>
    </article>;
  };
  const followUp = (note) => {
    setFollowUpError("");
    setFollowUpDraft({ id: note.id, patient_name: note.patient_name, patient_code: note.patient_code, health_centre: note.health_centre, message: note.follow_up || "" });
  };
  const saveHospitalFollowUp = async (event) => {
    event.preventDefault();
    if (!followUpDraft?.message.trim()) { setFollowUpError("Enter the follow-up action or outcome."); return; }
    setSavingReportId(followUpDraft.id); setFollowUpError("");
    try {
      await request(`/hospital/notifications/${followUpDraft.id}/follow-up`, { method: "POST", body: JSON.stringify({ note: followUpDraft.message }) });
      setFollowUpDraft(null); setMessage("Follow-up outcome recorded."); await loadHospital();
    } catch (e) { setFollowUpError(e.message); }
    finally { setSavingReportId(null); }
  };
  const recordAttendance = async (report) => {
    setError(""); setMessage("");
    try {
      await request(`/hospital/reports/${report.id}/attendance`, { method: "POST", body: JSON.stringify({ appointment_id: report.appointment?.id || null }) });
      setMessage("Hospital attendance recorded."); await loadHospital();
    } catch (e) { setError(e.message); }
  };
  useEffect(() => {
    if (!activeReportId && !reviewDraft && !appointmentDraft && !followUpDraft && !accountDialog) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") {
        setActiveReportId(null);
        setReviewDraft(null);
        setAppointmentDraft(null);
        setFollowUpDraft(null);
        setAccountDialog(null);
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [activeReportId, reviewDraft, appointmentDraft, followUpDraft, accountDialog]);
  const editHospital = async (h) => {
    const payload = { ...h };
    for (const [key, label] of [["name", "Hospital name"], ["code", "Hospital code"], ["district", "District"], ["state", "State"], ["address", "Address"], ["contact_number", "Contact number"], ["official_email", "Official email"]]) {
      const value = window.prompt(label, payload[key] || "");
      if (value === null) return;
      payload[key] = value;
    }
    await submit(`/admin/hospitals/${h.id}`, payload, "PATCH");
  };
  const editCentre = async (c) => {
    const payload = { ...c };
    for (const [key, label] of [["name", "Health-centre name"], ["code", "Health-centre code"], ["district", "District"], ["state", "State"], ["address", "Address"], ["contact_number", "Contact number"]]) {
      const value = window.prompt(label, payload[key] || "");
      if (value === null) return;
      payload[key] = value;
    }
    await submit(`/admin/health-centres/${c.id}`, payload, "PATCH");
  };

  return <div className="app network-app">
    <header className="header network-header"><div className="logo"><div className="logo-icon">G</div><div><h1>GlucoVision</h1><p>{user.role === "SUPER_ADMIN" ? "Super Admin · Hospital Network" : "Main Hospital · Clinical Oversight"}</p></div></div><button onClick={onLogout}>Logout</button></header>
    <main className="main-content network-content"><h2>{user.role === "SUPER_ADMIN" ? "Network administration" : "Hospital dashboard"}</h2>
      {accountDialog && <section className="network-panel" role="dialog" aria-modal="true" aria-labelledby="account-dialog-title"><h3 id="account-dialog-title">{accountDialog.mode === "reset" ? "Reset login password" : `Create ${accountDialog.type === "hospital" ? "hospital" : "health-centre"} login`}: {accountDialog.organisation.name}</h3><form className="network-form" onSubmit={saveAccount}>{accountDialog.mode === "create" && <><label>Username<input required minLength={3} maxLength={64} autoComplete="off" value={accountForm.username} onChange={(e) => setAccountForm({ ...accountForm, username: e.target.value })} /></label><label>Account holder name<input required value={accountForm.name} onChange={(e) => setAccountForm({ ...accountForm, name: e.target.value })} /></label></>}<label>{accountDialog.mode === "reset" ? "New password" : "Initial password"}<input type="password" required minLength={12} maxLength={128} autoComplete="new-password" value={accountForm.password} onChange={(e) => setAccountForm({ ...accountForm, password: e.target.value })} /></label><p>Use at least 12 characters. The password is stored as a hash and will not be shown again.</p><button className="analyze-button">{accountDialog.mode === "reset" ? "Reset password" : "Create account"}</button><button type="button" onClick={() => { setAccountDialog(null); setAccountForm({ username: "", name: "", password: "" }); }}>Cancel</button></form></section>}
      {message && <p className="success-message">{message}</p>}{error && <p className="error-message">{error}</p>}
      {user.role === "SUPER_ADMIN" && overview && <>
        <section className="network-stats">{[["Main hospitals", overview.hospitals], ["Health centres", overview.health_centres], ["Patients", overview.patients], ["Screening reports", overview.reports], ["Pending reviews", overview.pending_reviews], ["Missed follow-ups", overview.missed_follow_up]].map(([label, value]) => <article className="upload-card" key={label}><strong>{value}</strong><span>{label}</span></article>)}</section>
        {overview.awaiting_assignment > 0 && <p className="error-message">{overview.awaiting_assignment} screening report(s) are awaiting health-centre hospital assignment.</p>}
        <section className="network-panel"><h3>Main hospitals</h3><form className="network-form" onSubmit={(e) => { e.preventDefault(); submit("/admin/hospitals", hospitalForm).then(() => setHospitalForm(blankHospital)); }}>
          {[["name", "Hospital name"], ["code", "Unique code"], ["district", "District"], ["state", "State"], ["address", "Address"], ["contact_number", "Contact number"], ["official_email", "Official email"]].map(([key, label]) => <label key={key}>{label}<input required={key === "name" || key === "code"} value={hospitalForm[key]} onChange={(e) => setHospitalForm({ ...hospitalForm, [key]: e.target.value })} /></label>)}<button className="analyze-button">Add hospital</button></form>
          <div className="network-table">{hospitals.map((h) => <article key={h.id}><strong>{h.name} · {h.code || "Uncoded"}</strong><span>{h.district}, {h.state} · {h.is_active ? "Active" : "Inactive"}</span><span>{centres.filter((c) => c.assigned_hospital_id === h.id).length} centres · {h.pending_reports} pending reports · {h.missed_follow_up} missed follow-ups</span><span>Login account: {h.account_status === "active" ? "Active" : h.account_status === "disabled" ? "Disabled" : "Awaiting account creation"}</span>{h.account_status === "not_created" ? <button onClick={() => openAccountDialog("create", "hospital", h)}>Create login</button> : <><button onClick={() => submit(`/admin/accounts/hospital/${h.id}`, { is_active: h.account_status !== "active" }, "PATCH")}>{h.account_status === "active" ? "Disable login" : "Re-enable login"}</button><button onClick={() => openAccountDialog("reset", "hospital", h)}>Reset password</button></>}<button onClick={() => editHospital(h)}>Edit</button><button onClick={() => submit(`/admin/hospitals/${h.id}`, { ...h, is_active: !h.is_active }, "PATCH")}>{h.is_active ? "Deactivate" : "Activate"}</button></article>)}</div>
        </section>
        <section className="network-panel"><h3>Health centres and hospital assignment</h3><form className="network-form" onSubmit={(e) => { e.preventDefault(); const payload = { ...centreForm, assigned_hospital_id: centreForm.assigned_hospital_id ? Number(centreForm.assigned_hospital_id) : null }; submit("/admin/health-centres", payload).then(() => setCentreForm(blankCentre)); }}>
          {[["name", "Health-centre name"], ["code", "Unique code"], ["district", "District"], ["state", "State"], ["address", "Address"], ["contact_number", "Contact number"]].map(([key, label]) => <label key={key}>{label}<input required={key === "name" || key === "code"} value={centreForm[key]} onChange={(e) => setCentreForm({ ...centreForm, [key]: e.target.value })} /></label>)}<label>Assigned hospital<select value={centreForm.assigned_hospital_id} onChange={(e) => setCentreForm({ ...centreForm, assigned_hospital_id: e.target.value })}><option value="">Awaiting assignment</option>{hospitals.filter((h) => h.is_active).map((h) => <option key={h.id} value={h.id}>{h.name} · {h.code}</option>)}</select></label><button className="analyze-button">Add health centre</button></form>
          <label>Filter by district<select value={filter} onChange={(e) => setFilter(e.target.value)}><option value="">All districts</option>{districts.map((district) => <option key={district} value={district}>{district}</option>)}</select></label><label>Filter by hospital<select value={hospitalFilter} onChange={(e) => setHospitalFilter(e.target.value)}><option value="">All hospitals</option><option value="unassigned">Unassigned</option>{hospitals.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}</select></label><button type="button" onClick={() => { setFilter(""); setHospitalFilter(""); }}>Clear filters</button><p>{filteredCentres.length} health centre{filteredCentres.length === 1 ? "" : "s"} matching filters</p><div className="network-table">{filteredCentres.map((c) => <article key={c.id}><strong>{c.name} · {c.code || "Uncoded"}</strong><span>{c.district}, {c.state} · {c.hospital_name || "Awaiting hospital assignment"}</span><span>{c.patient_count} patients · {c.report_count} reports · {c.pending_reports} pending · {c.missed_follow_up} missed</span><span>Login account: {c.account_status === "active" ? "Active" : c.account_status === "disabled" ? "Disabled" : "Awaiting account creation"}</span>{c.account_status === "not_created" ? <button onClick={() => openAccountDialog("create", "health-centre", c)}>Create login</button> : <><button onClick={() => submit(`/admin/accounts/health-centre/${c.id}`, { is_active: c.account_status !== "active" }, "PATCH")}>{c.account_status === "active" ? "Disable login" : "Re-enable login"}</button><button onClick={() => openAccountDialog("reset", "health-centre", c)}>Reset password</button></>}<select aria-label={`Reassign ${c.name}`} value={c.assigned_hospital_id || ""} onChange={(e) => submit(`/admin/health-centres/${c.id}`, { ...c, assigned_hospital_id: e.target.value ? Number(e.target.value) : null }, "PATCH")}><option value="">Awaiting assignment</option>{hospitals.filter((h) => h.is_active).map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}</select><button onClick={() => editCentre(c)}>Edit</button><button onClick={() => submit(`/admin/health-centres/${c.id}`, { ...c, is_active: !c.is_active }, "PATCH")}>{c.is_active ? "Deactivate" : "Activate"}</button></article>)}</div>{filteredCentres.length === 0 && <p>No health centres match the selected filters.</p>}
        </section>
      </>}
      {user.role !== "SUPER_ADMIN" && hospitalLoading && <section className="network-panel loading-state" role="status">Loading hospital dashboard…</section>}
      {user.role !== "SUPER_ADMIN" && !hospitalLoading && !network && <section className="network-panel dashboard-load-error"><p>{error || "Hospital dashboard data is unavailable."}</p><button type="button" onClick={async () => { setHospitalLoading(true); setError(""); try { setNetwork(await request("/hospital/dashboard")); } catch (e) { setError(e.message); } finally { setHospitalLoading(false); } }}>Retry loading dashboard</button></section>}
      {user.role !== "SUPER_ADMIN" && network && <>
        <section className="network-panel hospital-patients-panel" id="screening-reports">
          <div className="panel-heading"><div><h3>{network.hospital?.name || "Hospital"} care dashboard</h3><p>Screening findings support triage. Clinical disposition and appointment status come from saved hospital records.</p></div><span className="panel-result-count">{patientRows.length} patients · {filteredReports.length} reports</span></div>
          <div className="network-form patient-search-filters">
            <label>Search patient or report<input value={patientSearch} onChange={(e) => setPatientSearch(e.target.value)} placeholder="Name, patient ID or report ID" /></label>
            <label>Health centre<select value={reportFilter.centre} onChange={(e) => setReportFilter({ ...reportFilter, centre: e.target.value })}><option value="">All centres</option>{network.health_centres.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
          </div>
          <div className="patient-tabs" role="tablist" aria-label="Patient care categories">{patientTabs.map((tab) => <button type="button" role="tab" aria-selected={activePatientTab === tab.id} className={activePatientTab === tab.id ? "active" : ""} key={tab.id} onClick={() => setActivePatientTab(tab.id)}>{tab.label}<span>{tab.rows.length}</span></button>)}</div>
          <div role="tabpanel" className="patient-category-list"><p className="category-description">{patientTabs.find((tab) => tab.id === activePatientTab)?.description}</p>{activePatientTab === "missed" ? missedAppointments.map(renderMissedAppointment) : patientTabs.find((tab) => tab.id === activePatientTab)?.rows.map(renderPatient)}{!patientTabs.find((tab) => tab.id === activePatientTab)?.rows.length && <p className="empty-state">{activePatientTab === "missed" ? "No missed appointments require follow-up." : "No patients match this category and the selected filters."}</p>}{activePatientTab === "missed" && !!otherFollowUps.length && <section className="notification-followups"><h3>Referral attendance alerts</h3>{otherFollowUps.map((n) => <article key={n.id}><div><strong>{n.patient_name} · Patient ID {n.patient_code} · {n.health_centre}</strong><span>{n.message}</span><span>{n.resolved_at ? "Attendance recorded; alert resolved" : n.follow_up_at ? `Hospital follow-up: ${n.follow_up}` : "Health-centre follow-up required"}</span></div><button type="button" onClick={() => followUp(n)}>{n.follow_up_at ? "Update Follow-up" : "Record Follow-up"}</button></article>)}</section>}</div>
        </section>
        {!!upcomingAppointments.length && <section className="network-panel upcoming-appointments-panel"><h3>Upcoming appointments <span>{upcomingAppointments.length}</span></h3><div className="upcoming-appointments-list">{upcomingAppointments.map((a) => <article key={a.id}><div><strong>{a.patient_name} · {a.patient_code}</strong><span>Report #{a.screening_id || "—"} · {a.health_centre}</span><span>{new Date(a.appointment_datetime).toLocaleString()} · Dr. {a.doctor_name} · {a.status}</span></div><button type="button" onClick={() => setAppointmentDraft({ kind: "reschedule", id: a.id, reportId: a.screening_id, doctor_name: a.doctor_name || "", appointment_datetime: localDateTimeInput(a.appointment_datetime), notes: a.notes || "" })}>Reschedule</button><button type="button" onClick={() => updateAppointment(a.id, { status: "ATTENDED" })}>Record Attendance</button><button type="button" onClick={() => updateAppointment(a.id, { status: "CANCELLED" })}>Cancel</button></article>)}</div></section>}

        {activeReport && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setActiveReportId(null); }}>
          <section className="dashboard-modal report-modal" role="dialog" aria-modal="true" aria-labelledby="complete-report-title">
            <header className="modal-header"><div><span className="eyebrow">Original screening report · Report #{activeReport.id}</span><h2 id="complete-report-title">{activeReport.patient_name} · {activeReport.patient_code}</h2></div><button type="button" className="modal-close" aria-label="Close complete report" onClick={() => setActiveReportId(null)}>Close</button></header>
            <div className="modal-body">
              <section className="report-section"><h3>Patient and referral</h3><div className="report-facts"><p><strong>Age / sex</strong><span>{activeReport.patient_age ?? "Not recorded"} · {activeReport.patient_sex || "Not recorded"}</span></p><p><strong>Phone</strong><span>{activeReport.patient_phone || "Not recorded"}</span></p><p><strong>Screening date</strong><span>{activeReport.screening_date ? new Date(activeReport.screening_date).toLocaleString() : "Not recorded"}</span></p><p><strong>Report ID</strong><span>#{activeReport.id}</span></p><p><strong>Originating health centre</strong><span>{cleanLabel(activeReport.health_centre) || "Not recorded"}</span></p><p><strong>Assigned hospital</strong><span>{cleanLabel(network?.hospital?.name) || "Not recorded"}</span></p><p><strong>Referral</strong><span>{activeReport.submitted_at ? `Submitted ${new Date(activeReport.submitted_at).toLocaleString()}` : "Not submitted"}</span></p><p><strong>Hospital attendance</strong><span>{activeReport.hospital_attended_at ? new Date(activeReport.hospital_attended_at).toLocaleString() : "Not recorded"}</span></p></div></section>
              <section className="report-section ai-report-section"><div><span className="eyebrow">AI screening · Not a doctor's assessment</span><h3>{activeReport.prediction || "Finding not recorded"}</h3><p>Model confidence: <strong>{formatPercent(activeReport.confidence)}</strong></p></div><div className="score-table-wrap"><table><thead><tr><th>Model class</th><th>Stored score</th></tr></thead><tbody>{Object.entries(activeReport.probabilities || {}).map(([label, score]) => <tr key={label}><td>{label}</td><td>{formatPercent(score)}</td></tr>)}</tbody></table>{!Object.keys(activeReport.probabilities || {}).length && <p className="empty-state">Class scores are not available for this screening.</p>}</div><p className="report-disclaimer">This AI-assisted screening supports triage. It is not a definitive diagnosis or a clinical recommendation.</p></section>
              <section className="report-section"><h3>Retinal images</h3><div className="report-image-grid">{activeReport.original_image_url ? <figure><figcaption>Original retinal image</figcaption><AuthenticatedImage src={activeReport.original_image_url} token={user.session_token} alt={`Original retinal image for report ${activeReport.id}`} className="report-image" /></figure> : <p className="empty-state">Original retinal image is unavailable for this legacy report.</p>}{activeReport.gradcam_image_path ? <figure><figcaption>Grad-CAM model explanation</figcaption><AuthenticatedImage src={activeReport.gradcam_image_path} token={user.session_token} alt={`Grad-CAM explanation for report ${activeReport.id}`} className="report-image" /></figure> : <p className="empty-state">Grad-CAM explanation is not available for this screening.</p>}</div></section>
              <section className="report-section clinical-summary"><h3>Hospital clinical review</h3><p><strong>Doctor:</strong> {activeReport.doctor_name || "Not recorded"} · <strong>Review date:</strong> {activeReport.clinical_reviewed_at ? new Date(activeReport.clinical_reviewed_at).toLocaleString() : "Not reviewed"}</p><p><strong>Assessment:</strong> {activeReport.clinical_review_notes || "Not recorded"}</p><p><strong>Recommendations:</strong> {activeReport.recommendations || "Not recorded"}</p><p><strong>Follow-up priority:</strong> {activeReport.follow_up_priority || (activeReport.clinically_flagged ? "Flagged" : "Not recorded")}</p><p><strong>Follow-up status:</strong> {followUpStatus(activeReport)}</p><p><strong>Clinical disposition:</strong> {dispositionLabel(activeReport.clinical_disposition)}</p>{activeReport.clinical_outcome && <p><strong>Care completion outcome:</strong> {outcomeLabels[activeReport.clinical_outcome] || activeReport.clinical_outcome}</p>}<p><strong>Consultation:</strong> {activeReport.appointment ? `${new Date(activeReport.appointment.appointment_datetime).toLocaleString()} · ${activeReport.appointment.status} · Dr. ${activeReport.appointment.doctor_name}` : "Not scheduled"}</p></section>
              <div className="report-modal-actions">{activeReport.original_pdf_available ? <><button type="button" onClick={() => openOriginalPdf(activeReport.id)}>View Original Screening PDF</button><button type="button" onClick={() => downloadOriginalPdf(activeReport.id)}>Download Original Screening PDF</button><button type="button" onClick={() => printOriginalPdf(activeReport.id)}>Print Report</button></> : <p className="empty-state">The original screening PDF is unavailable for this legacy report. No replacement PDF has been created.</p>}<button type="button" onClick={() => { startReview(activeReport); setActiveReportId(null); }}>Clinical Review</button><button type="button" onClick={() => { startAppointment(activeReport); setActiveReportId(null); }}>Appointment</button>{!activeReport.hospital_attended_at && <button type="button" onClick={() => recordAttendance(activeReport)}>Record Attendance</button>}</div>
            </div>
          </section>
        </div>}
        {reviewDraft && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !savingReportId) setReviewDraft(null); }}>
          <section className="dashboard-modal form-modal" role="dialog" aria-modal="true" aria-labelledby="clinical-review-title"><header className="modal-header"><div><span className="eyebrow">Report #{reviewDraft.id} · Separate from AI screening</span><h2 id="clinical-review-title">Clinical review</h2></div><button type="button" className="modal-close" disabled={Boolean(savingReportId)} onClick={() => setReviewDraft(null)}>Close</button></header>
            <form className="clinical-review-form network-form" onSubmit={saveReview}><p className="form-help">Save the clinician's assessment and care plan. This does not alter the original screening result.</p>
              <section className="review-form-section"><h3>1. Doctor's Assessment</h3><label>Reviewing doctor's name<input required autoComplete="name" value={reviewDraft.doctor_name} onChange={(e) => setReviewDraft({ ...reviewDraft, doctor_name: e.target.value })} /></label><label className="wide-field">Clinical assessment<textarea required rows="6" value={reviewDraft.notes} onChange={(e) => setReviewDraft({ ...reviewDraft, notes: e.target.value })} placeholder="Document the clinical assessment" /></label><label className="wide-field">Recommendations or follow-up instructions <span className="optional-label">Optional except for Stable — Monitoring</span><textarea rows="3" value={reviewDraft.recommendations} onChange={(e) => setReviewDraft({ ...reviewDraft, recommendations: e.target.value })} placeholder="Document recommendations and next steps" /></label><div className="review-independent-controls"><label>Follow-up priority<select value={reviewDraft.follow_up_priority} onChange={(e) => setReviewDraft({ ...reviewDraft, follow_up_priority: e.target.value })}><option value="ROUTINE">Routine</option><option value="PRIORITY">Priority</option><option value="URGENT">Urgent</option></select><span className="form-help">Clinical urgency remains separate from disposition.</span></label><label className="followup-checkbox"><input type="checkbox" checked={reviewDraft.flagged} onChange={(e) => setReviewDraft({ ...reviewDraft, flagged: e.target.checked })} />Flag for clinical attention</label></div></section>
              <section className="review-form-section"><h3>2. Care Decision</h3><div className="care-decision-explanations"><p><strong>Follow-up Required:</strong> Further assessment, treatment or another consultation is needed.</p><p><strong>Stable — Monitoring:</strong> The patient is stable with a documented monitoring plan.</p><p><strong>Completed / Discharged:</strong> The current hospital care episode has formally ended.</p></div><label className="wide-field">Clinical disposition<select required value={reviewDraft.clinical_disposition} onChange={(e) => setReviewDraft({ ...reviewDraft, clinical_disposition: e.target.value, clinical_outcome: "", follow_up_required: ["FOLLOW_UP_REQUIRED", "STABLE_MONITORING"].includes(e.target.value) })}><option value="">Choose a care decision</option><option value="FOLLOW_UP_REQUIRED">Follow-up Required</option><option value="STABLE_MONITORING">Stable — Monitoring</option><option value="DISCHARGED_CARE_COMPLETED">Completed / Discharged</option></select></label>{reviewDraft.clinical_disposition === "DISCHARGED_CARE_COMPLETED" && <><p className="form-help">AI screening alone does not establish recovery; record only the documented outcome.</p><label className="wide-field">Documented outcome<select required value={reviewDraft.clinical_outcome} onChange={(e) => setReviewDraft({ ...reviewDraft, clinical_outcome: e.target.value })}><option value="">Choose documented outcome</option><option value="RECOVERED">Recovered as documented</option><option value="DISCHARGED_WITHOUT_DOCUMENTED_RECOVERY">Discharged without documented recovery</option></select></label></>}</section>
              <section className="review-form-section"><h3>3. Next Appointment</h3>{["FOLLOW_UP_REQUIRED", "STABLE_MONITORING"].includes(reviewDraft.clinical_disposition) ? <><p className="form-help">A future date and time are required. The appointment is saved with this clinical review.</p><label>Appointment date and time<input type="datetime-local" required value={reviewDraft.appointment_datetime} onChange={(e) => setReviewDraft({ ...reviewDraft, appointment_datetime: e.target.value })} /></label><label>Appointment instructions<textarea rows="2" value={reviewDraft.appointment_notes} onChange={(e) => setReviewDraft({ ...reviewDraft, appointment_notes: e.target.value })} placeholder="Optional instructions for the appointment" /></label></> : <p className="form-help">Choose an active-care decision to require a next appointment. Completed / Discharged does not require a new appointment.</p>}</section>
              {reviewDraft.reviewed_at && <p className="form-help">Previously reviewed {new Date(reviewDraft.reviewed_at).toLocaleString()}</p>}{reviewError && <p className="error-message" role="alert">{reviewError}</p>}
              <div className="modal-form-actions"><button className="primary-action" disabled={savingReportId === reviewDraft.id}>{savingReportId === reviewDraft.id ? "Saving review…" : "Save Clinical Review"}</button><button type="button" disabled={savingReportId === reviewDraft.id} onClick={() => { setReviewDraft(null); setReviewError(""); }}>Cancel</button></div>
            </form>
          </section>
        </div>}
        {appointmentDraft && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !savingReportId) setAppointmentDraft(null); }}>
          <section className="dashboard-modal form-modal" role="dialog" aria-modal="true" aria-labelledby="appointment-title"><header className="modal-header"><div><span className="eyebrow">Report #{appointmentDraft.reportId || "—"}</span><h2 id="appointment-title">{appointmentDraft.kind === "reschedule" ? "Reschedule consultation" : "Schedule consultation"}</h2></div><button type="button" className="modal-close" disabled={Boolean(savingReportId)} onClick={() => setAppointmentDraft(null)}>Close</button></header>
            <form className="clinical-review-form network-form" onSubmit={saveAppointment}><p className="form-help">Appointments do not count as attendance until hospital staff record the patient's arrival.</p>
              <label>Reviewing doctor<input required value={appointmentDraft.doctor_name} onChange={(e) => setAppointmentDraft({ ...appointmentDraft, doctor_name: e.target.value })} /></label>
              <label>Consultation date and time<input type="datetime-local" required min={localDateTimeInput(new Date().toISOString())} value={appointmentDraft.appointment_datetime} onChange={(e) => setAppointmentDraft({ ...appointmentDraft, appointment_datetime: e.target.value })} /></label>
              <label className="wide-field">Appointment notes / follow-up instructions<textarea rows="4" value={appointmentDraft.notes} onChange={(e) => setAppointmentDraft({ ...appointmentDraft, notes: e.target.value })} /></label>
              {appointmentError && <p className="error-message" role="alert">{appointmentError}</p>}
              <div className="modal-form-actions"><button className="primary-action" disabled={savingReportId === appointmentDraft.id}>{savingReportId === appointmentDraft.id ? "Saving…" : appointmentDraft.kind === "reschedule" ? "Save Reschedule" : "Schedule Consultation"}</button>{appointmentDraft.kind === "reschedule" && <button type="button" disabled={Boolean(savingReportId)} onClick={async () => { const updated = await updateAppointment(appointmentDraft.id, { status: "CANCELLED" }); if (updated) setAppointmentDraft(null); }}>Cancel Consultation</button>}<button type="button" disabled={Boolean(savingReportId)} onClick={() => setAppointmentDraft(null)}>Close</button></div>
            </form>
          </section>
        </div>}
        {followUpDraft && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !savingReportId) setFollowUpDraft(null); }}>
          <section className="dashboard-modal form-modal" role="dialog" aria-modal="true" aria-labelledby="followup-title"><header className="modal-header"><div><span className="eyebrow">{followUpDraft.health_centre || "Originating health centre"} · {followUpDraft.patient_code}</span><h2 id="followup-title">Record follow-up outcome</h2></div><button type="button" className="modal-close" disabled={Boolean(savingReportId)} onClick={() => setFollowUpDraft(null)}>Close</button></header>
            <form className="clinical-review-form network-form" onSubmit={saveHospitalFollowUp}><p className="form-help"><strong>{followUpDraft.patient_name}</strong> · {followUpDraft.message || "Document the contact, next action or follow-up result."}</p><label className="wide-field">Follow-up action or outcome<textarea required rows="5" value={followUpDraft.message} onChange={(event) => setFollowUpDraft({ ...followUpDraft, message: event.target.value })} placeholder="Document the action taken and any next step" /></label>{followUpError && <p className="error-message" role="alert">{followUpError}</p>}<div className="modal-form-actions"><button className="primary-action" disabled={savingReportId === followUpDraft.id}>{savingReportId === followUpDraft.id ? "Saving outcome…" : "Save Follow-up Outcome"}</button><button type="button" disabled={savingReportId === followUpDraft.id} onClick={() => setFollowUpDraft(null)}>Cancel</button></div></form>
          </section>
        </div>}
      </>}
    </main>
  </div>;
}
