const fileInput = document.querySelector("#files");
const dropZone = document.querySelector("#drop-zone");
const selection = document.querySelector("#selection");
const uploadButton = document.querySelector("#upload");
const message = document.querySelector("#message");
const results = document.querySelector("#results");
const summary = document.querySelector("#summary");
const template = document.querySelector("#job-template");

const MAX_CONCURRENCY = 5;
const MAX_ATTEMPTS = 3;
let selectedFiles = [];
let jobs = [];

function setFiles(files) {
  selectedFiles = [...files].filter(
    (file) => file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf"),
  );
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

function delay(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function displayResult(job) {
  if (!job.result) return { error: job.error || "Waiting for extraction" };
  if (!job.result.personImageBase64) return job.result;
  return {
    ...job.result,
    personImageBase64: `[image base64 omitted — ${job.result.personImageBase64.length.toLocaleString()} characters]`,
  };
}

function createCard(job) {
  const fragment = template.content.cloneNode(true);
  const card = fragment.querySelector(".job-card");
  card.dataset.jobId = job.id;
  results.append(fragment);
  return results.querySelector(`[data-job-id="${job.id}"]`);
}

function renderJob(job) {
  const card = results.querySelector(`[data-job-id="${job.id}"]`) || createCard(job);
  card.querySelector(".job-name").textContent = job.file.name;
  card.querySelector(".job-id").textContent = job.id;

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

  const json = JSON.stringify(displayResult(job), null, 2);
  card.querySelector(".json-output").textContent = json;
  const copyButton = card.querySelector(".copy-button");
  copyButton.disabled = !job.result;
  copyButton.onclick = async () => {
    await navigator.clipboard.writeText(JSON.stringify(job.result, null, 2));
    copyButton.textContent = "Copied";
    window.setTimeout(() => { copyButton.textContent = "Copy JSON"; }, 1200);
  };
}

function updateSummary() {
  const count = (status) => jobs.filter((job) => job.status === status).length;
  summary.textContent = `${count("done")} done · ${count("processing")} processing · ${count("queued")} queued · ${count("failed")} failed`;
}

async function extractWithRetry(job) {
  job.status = "processing";
  renderJob(job);
  updateSummary();

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    const form = new FormData();
    form.append("file", job.file);
    try {
      const response = await fetch("/extract", { method: "POST", body: form });
      const body = await response.json();
      if (!response.ok) {
        const error = new Error(body.detail || `Extraction failed (${response.status})`);
        error.retryable = response.status >= 500;
        throw error;
      }
      job.result = body;
      job.error = null;
      job.status = "done";
      renderJob(job);
      updateSummary();
      return;
    } catch (error) {
      const retryable = error.retryable !== false;
      if (!retryable || attempt === MAX_ATTEMPTS) {
        job.error = error.message || "Network request failed";
        job.status = "failed";
        renderJob(job);
        updateSummary();
        return;
      }
      await delay(500 * (2 ** (attempt - 1)));
    }
  }
}

async function uploadFiles() {
  if (!selectedFiles.length) return;

  uploadButton.disabled = true;
  fileInput.disabled = true;
  results.innerHTML = "";
  setMessage("Extracting PDFs…");

  jobs = selectedFiles.map((file, index) => ({
    id: globalThis.crypto?.randomUUID?.() || `file-${Date.now()}-${index}`,
    file,
    status: "queued",
    result: null,
    error: null,
  }));
  jobs.forEach(renderJob);
  updateSummary();

  let nextIndex = 0;
  async function worker() {
    while (nextIndex < jobs.length) {
      const job = jobs[nextIndex];
      nextIndex += 1;
      await extractWithRetry(job);
    }
  }

  const workerCount = Math.min(MAX_CONCURRENCY, jobs.length);
  await Promise.all(Array.from({ length: workerCount }, worker));

  const failed = jobs.filter((job) => job.status === "failed").length;
  setMessage(
    failed
      ? `Finished with ${failed} failed file${failed === 1 ? "" : "s"}. Successful results remain available below.`
      : `Finished extracting ${jobs.length} file${jobs.length === 1 ? "" : "s"}.`,
    failed > 0,
  );
  fileInput.disabled = false;
  uploadButton.disabled = selectedFiles.length === 0;
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
