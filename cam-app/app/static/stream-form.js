/** Client-side validation for the schedule-stream form. */

const GC_STREAM_KEY_MIN_LENGTH = 40;
const YT_STREAM_KEY_MIN_LENGTH = 20;

/** GameChanger: sk_{region}_{secret}[?gc_ext=true] */
const GC_STREAM_KEY_RE = /^sk_[a-z0-9-]+_[A-Za-z0-9_-]+(\?gc_ext=true)?$/;

/** YouTube: groups of four lowercase alphanumeric chars separated by dashes. */
const YT_STREAM_KEY_RE = /^[a-z0-9]{4}(-[a-z0-9]{4}){3,}$/;

/** RTMP/RTMPS base URL or SRT caller URL with host:port. */
const CUSTOM_RTMP_URL_RE = /^rtmps?:\/\/.+/i;
const CUSTOM_SRT_URL_RE = /^srt:\/\/[^/?#\s]+:\d+(?:[/?#].*)?$/i;

/**
 * If the user pasted a full GameChanger RTMP(S) URL, return only the stream key.
 * @param {string} input
 * @returns {string}
 */
function extractGcStreamKey(input) {
    input = input.trim();
    if (!/^rtmps?:\/\//i.test(input)) {
        return input;
    }
    try {
        const url = new URL(input);
        const segments = url.pathname.split("/").filter(Boolean);
        const keySegment = segments.length ? segments[segments.length - 1] : "";
        if (!keySegment) {
            return input;
        }
        return keySegment + url.search;
    } catch (_err) {
        const match = input.match(/\/app\/([^/?#]+(?:\?[^#]*)?)/i);
        return match ? match[1] : input;
    }
}

/**
 * @param {string} value
 * @param {'gamechanger'|'youtube'|'custom'} destination
 * @returns {{ valid: boolean, message: string }}
 */
function validateStreamKey(value, destination) {
    value = value.trim();
    if (!value) {
        return { valid: false, message: "Stream key is required." };
    }
    if (destination === "gamechanger") {
        if (value.length < GC_STREAM_KEY_MIN_LENGTH) {
            return {
                valid: false,
                message: "GameChanger stream keys are longer — paste the full key (sk_us-east-1_…).",
            };
        }
        if (!GC_STREAM_KEY_RE.test(value)) {
            return {
                valid: false,
                message: "GameChanger key should look like sk_us-east-1_…?gc_ext=true",
            };
        }
        return { valid: true, message: "" };
    }
    if (destination === "youtube") {
        if (value.length < YT_STREAM_KEY_MIN_LENGTH) {
            return {
                valid: false,
                message: "YouTube stream keys are longer — use the full key from YouTube Studio.",
            };
        }
        if (!YT_STREAM_KEY_RE.test(value)) {
            return {
                valid: false,
                message: "YouTube key should look like 2grb-me60-4194-d5at-0hg9",
            };
        }
        return { valid: true, message: "" };
    }
    return { valid: true, message: "" };
}

/**
 * @param {string} value
 * @returns {{ valid: boolean, message: string }}
 */
function validateCustomUrl(value) {
    value = value.trim();
    if (!value) {
        return { valid: false, message: "Custom stream URL is required." };
    }
    if (CUSTOM_RTMP_URL_RE.test(value) || CUSTOM_SRT_URL_RE.test(value)) {
        return { valid: true, message: "" };
    }
    return {
        valid: false,
        message: "Use rtmp://, rtmps://, or an SRT caller URL like srt://host:port",
    };
}

/**
 * @param {HTMLFormElement|null} form
 * @returns {boolean}
 */
function applyScheduleFormValidation(form) {
    if (!form) {
        return false;
    }
    const destInput = form.querySelector('[name="destination"]:checked');
    const destination = destInput ? destInput.value : "gamechanger";
    const streamKeyEl = form.querySelector("#add-streamKey");
    const customUrlEl = form.querySelector("#add-customUrl");

    if (streamKeyEl) {
        let keyValue = streamKeyEl.value.trim();
        if (destination === "gamechanger") {
            const extracted = extractGcStreamKey(keyValue);
            if (extracted !== keyValue) {
                streamKeyEl.value = extracted;
                keyValue = extracted;
            }
        }
        const keyResult = validateStreamKey(keyValue, destination);
        streamKeyEl.setCustomValidity(keyResult.valid ? "" : keyResult.message);
    }

    if (destination === "custom" && customUrlEl) {
        const urlResult = validateCustomUrl(customUrlEl.value);
        customUrlEl.setCustomValidity(urlResult.valid ? "" : urlResult.message);
    } else if (customUrlEl) {
        customUrlEl.setCustomValidity("");
    }

    return form.reportValidity();
}

/**
 * @param {HTMLElement} btn
 * @returns {boolean}
 */
function prepareScheduleForm(btn) {
    return applyScheduleFormValidation(btn.closest("form"));
}

/**
 * @param {HTMLInputElement} input
 */
function validateStreamKeyInput(input) {
    const form = input.closest("form");
    if (!form) {
        return;
    }
    const destInput = form.querySelector('[name="destination"]:checked');
    const destination = destInput ? destInput.value : "gamechanger";
    let value = input.value.trim();
    if (destination === "gamechanger") {
        const extracted = extractGcStreamKey(value);
        if (extracted !== value) {
            input.value = extracted;
            value = extracted;
        }
    }
    const result = validateStreamKey(value, destination);
    input.setCustomValidity(result.valid ? "" : result.message);
}

/**
 * @param {HTMLInputElement} input
 */
function validateCustomUrlInput(input) {
    const result = validateCustomUrl(input.value);
    input.setCustomValidity(result.valid ? "" : result.message);
}
