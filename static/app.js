const districtInput = document.querySelector("#district");
const fileInput = document.querySelector("#files");
const dropZone = document.querySelector("#drop-zone");
const selection = document.querySelector("#selection");
const uploadButton = document.querySelector("#upload");
const message = document.querySelector("#message");
const results = document.querySelector("#results");
const summary = document.querySelector("#summary");
const template = document.querySelector("#job-template");

let selectedFiles = [];
let pollTimer = null;

function setFiles(files) {
  selectedFiles = [...files].filter((file) => file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf"));
  if (selectedFiles.length > 100) {
    selectedFiles = selectedFiles.slice(0, 100);
    setMessage("Only the first 100 PDFs were selected.", true);
  }
  selection.textContent = selectedFiles.length
    ? `${selectedFiles.length} file${selectedFiles.length === 1 ? "" : "s"}: ${selectedFiles.map((file) => file.name).join(", ")}`
    : "No files selected";
  uploadButton.disabled = selectedFiles.length === 0;
}

function setMessage(text, isError = false) {
  message.textContent = text;
  message.classList.toggle("error", isError);
}

function shortenedResult(job) {
  const payload = {
    job_id: job.job_id,
    file_name: job.file_name,
    district_id: job.district_id,
    status: job.status,
    result: job.result,
    error: job.error,
  };
  if (payload.result?.personImageBase64) {
    const length = payload.result.personImageBase64.length;
    payload.result = { ...payload.result, personImageBase64: `[image base64 omitted — ${length.toLocaleString()} characters]` };
  }
  return payload;
}

function createCard(job) {
  const fragment = template.content.cloneNode(true);
  const card = fragment.querySelector(".job-card");
  card.dataset.jobId = job.job_id;
  results.append(fragment);
  return results.querySelector(`[data-job-id="${job.job_id}"]`);
}

function renderJob(job) {
  const card = results.querySelector(`[data-job-id="${job.job_id}"]`) || createCard(job);
  card.querySelector(".job-name").textContent = job.file_name;
  card.querySelector(".job-id").textContent = job.job_id;

  const pill = card.querySelector(".status-pill");
  pill.textContent = job.status;
  pill.className = `status-pill ${job.status}`;

  const photoWrap = card.querySelector(".photo-wrap");
  const photo = card.querySelector(".photo");
  if (job.result?.personImageBase64) {
    photo.src = job.result.personImageBase64;
    photoWrap.hidden = false;
  } else {
    photo.removeAttribute("src");
    photoWrap.hidden = true;
  }

  const displayPayload = shortenedResult(job);
  const json = JSON.stringify(displayPayload, null, 2);
  card.querySelector(".json-output").textContent = json;
  const copyButton = card.querySelector(".copy-button");
  copyButton.onclick = async () => {
    await navigator.clipboard.writeText(json);
    copyButton.textContent = "Copied";
    window.setTimeout(() => { copyButton.textContent = "Copy JSON"; }, 1200);
  };
}

function updateSummary(batch) {
  summary.textContent = `${batch.done} done · ${batch.processing} processing · ${batch.queued} queued · ${batch.failed} failed`;
}

async function fetchBatch(batchId) {
  const response = await fetch(`/batches/${batchId}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Could not load batch (${response.status})`);
  return response.json();
}

async function pollBatch(batchId) {
  try {
    const batch = await fetchBatch(batchId);
    batch.results.forEach(renderJob);
    updateSummary(batch);
    const finished = batch.done + batch.failed === batch.total;
    if (finished) {
      setMessage(`Finished processing ${batch.total} file${batch.total === 1 ? "" : "s"}.`);
      pollTimer = null;
      return;
    }
    pollTimer = window.setTimeout(() => pollBatch(batchId), 1000);
  } catch (error) {
    setMessage(error.message, true);
    pollTimer = window.setTimeout(() => pollBatch(batchId), 2500);
  }
}

async function uploadFiles() {
  const district = districtInput.value.trim();
  if (!district) {
    setMessage("Enter a district ID.", true);
    districtInput.focus();
    return;
  }
  if (!selectedFiles.length) return;

  window.clearTimeout(pollTimer);
  uploadButton.disabled = true;
  setMessage("Uploading PDFs…");
  results.innerHTML = "";
  summary.textContent = "";

  const form = new FormData();
  selectedFiles.forEach((file) => form.append("files", file));
  try {
    const response = await fetch(`/districts/${encodeURIComponent(district)}/batches`, { method: "POST", body: form });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || `Upload failed (${response.status})`);

    body.jobs.forEach((job) => renderJob({ ...job, district_id: district, result: null, error: null }));
    setMessage(`Batch ${body.batch_id} accepted. Processing…`);
    await pollBatch(body.batch_id);
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    uploadButton.disabled = selectedFiles.length === 0;
  }
}

fileInput.addEventListener("change", () => setFiles(fileInput.files));
uploadButton.addEventListener("click", uploadFiles);
["dragenter", "dragover"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
  event.preventDefault();
  dropZone.classList.add("dragging");
}));
["dragleave", "drop"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
  event.preventDefault();
  dropZone.classList.remove("dragging");
}));
dropZone.addEventListener("drop", (event) => setFiles(event.dataTransfer.files));
