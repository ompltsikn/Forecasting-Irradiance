#!/usr/bin/env bash
set -Eeuo pipefail

profile=""
model=""
destination=""
issue_time_utc=""

while (($#)); do
  case "$1" in
    --profile) profile="${2:?}"; shift 2 ;;
    --model) model="${2:?}"; shift 2 ;;
    --destination) destination="${2:?}"; shift 2 ;;
    --issue-time-utc) issue_time_utc="${2:?}"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ "${profile}" =~ ^(smoke|full|catchup|scheduled)$ ]] || {
  echo "Invalid profile: ${profile}" >&2; exit 2;
}
[[ "${model}" =~ ^(ifs|aifs-single)$ ]] || {
  echo "Invalid model: ${model}" >&2; exit 2;
}
[[ "${destination}" == gdrive:* && "${destination}" != "gdrive:" ]] || {
  echo "NWP destination must be a non-root gdrive: path" >&2; exit 2;
}
[[ "${destination}" != *$'\n'* && "${destination}" != *".."* ]] || {
  echo "Unsafe NWP destination" >&2; exit 2;
}
[[ -n "${RCLONE_CONFIG:-}" && -s "${RCLONE_CONFIG}" ]] || {
  echo "RCLONE_CONFIG is missing or empty" >&2; exit 2;
}
if [[ "${profile}" =~ ^(catchup|scheduled)$ && -n "${issue_time_utc}" ]]; then
  echo "--issue-time-utc is not allowed for ${profile}" >&2
  exit 2
fi

runner_temp="${RUNNER_TEMP:-/tmp}"
if [[ -n "${NWP_WORK_ROOT:-}" ]]; then
  work_root="${NWP_WORK_ROOT}"
  [[ "${work_root}" == "${runner_temp%/}"/nwp-archiver-* ]] || {
    echo "NWP_WORK_ROOT must be a dedicated child of RUNNER_TEMP" >&2; exit 2;
  }
  [[ ! -e "${work_root}" ]] || {
    echo "NWP_WORK_ROOT already exists: ${work_root}" >&2; exit 2;
  }
  install -d -m 700 "${work_root}"
else
  work_root="$(mktemp -d "${runner_temp%/}/nwp-archiver.XXXXXX")"
fi
output_root="${work_root}/outbox"
verify_root="${work_root}/verify"
mkdir -p "${output_root}" "${verify_root}"

cleanup() {
  rm -rf -- "${work_root}"
}
trap cleanup EXIT

summary() {
  local line="$1"
  printf '%s\n' "${line}"
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    printf '%s\n' "${line}" >> "${GITHUB_STEP_SUMMARY}"
  fi
}

current_issue="not-started"
report_failure() {
  local status=$?
  trap - ERR
  summary "- ${model} ${current_issue}: failed (exit=${status})"
  exit "${status}"
}
trap report_failure ERR

summary_manifest() {
  local archive_status="$1"
  local manifest="$2"
  local remote_path="$3"
  local manifest_issue latency rows parameters grid_lat grid_lon distance
  local valid_min valid_max
  manifest_issue="$(jq -er '.issue_time_utc' <<< "${manifest}")"
  latency="$(jq -er '
    ((.retrieved_at_utc | fromdateiso8601) -
     (.issue_time_utc | fromdateiso8601)) / 60
  ' <<< "${manifest}")"
  rows="$(jq -er '.row_count' <<< "${manifest}")"
  parameters="$(jq -er '.received_parameters | length' <<< "${manifest}")"
  grid_lat="$(jq -er '.grid_latitude' <<< "${manifest}")"
  grid_lon="$(jq -er '.grid_longitude' <<< "${manifest}")"
  distance="$(jq -er '.grid_distance_km' <<< "${manifest}")"
  valid_min="$(jq -er '.valid_time_min_utc' <<< "${manifest}")"
  valid_max="$(jq -er '.valid_time_max_utc' <<< "${manifest}")"
  summary "- ${model} ${manifest_issue}: ${archive_status}; latency_min=${latency}; rows=${rows}; parameters=${parameters}; grid=${grid_lat},${grid_lon}; distance_km=${distance}; valid_range=${valid_min}..${valid_max}; path=${remote_path}"
}

committed_manifest=""
committed_remote_base=""
manifest_is_committed() {
  local partition="$1"
  local issue="$2"
  local source="$3"
  local listing
  if ! listing="$(rclone lsf "${destination}" \
      --config "${RCLONE_CONFIG}" \
      --recursive --files-only \
      --include "${partition}/retrieved_at=*/manifest.json")"; then
    echo "Drive manifest listing failed for ${partition}" >&2
    return 2
  fi
  local path
  while IFS= read -r path; do
    [[ -n "${path}" ]] || continue
    local manifest
    if ! manifest="$(rclone cat "${destination}/${path}" --config "${RCLONE_CONFIG}")"; then
      echo "Drive manifest read failed: ${path}" >&2
      return 2
    fi
    if ! jq -e --arg issue "${issue}" --arg source "${source}" --arg model "${model}" '
        type == "object" and
        .status == "complete" and
        .schema_version == 1 and
        .issue_time_utc == $issue and
        .nwp_source == $source and
        .nwp_model == $model and
        (.retrieved_at_utc | type == "string") and
        (.requested_parameters | type == "array" and length > 0) and
        (.received_parameters | type == "array" and length > 0) and
        ((.requested_parameters | length) == (.requested_parameters | unique | length)) and
        ((.received_parameters | length) == (.received_parameters | unique | length)) and
        ((.requested_parameters | sort) == (.received_parameters | sort)) and
        (.requested_steps_h | type == "array" and length > 0) and
        (.received_steps_h | type == "array" and length > 0) and
        ((.requested_steps_h | length) == (.requested_steps_h | unique | length)) and
        ((.received_steps_h | length) == (.received_steps_h | unique | length)) and
        ((.requested_steps_h | sort) == (.received_steps_h | sort)) and
        (.row_count | type == "number" and . > 0) and
        (.grid_latitude | type == "number") and
        (.grid_longitude | type == "number") and
        (.grid_distance_km | type == "number" and . >= 0 and . <= 25) and
        (.parquet_bytes | type == "number" and . > 0) and
        (.parquet_sha256 | type == "string" and test("^[0-9a-f]{64}$")) and
        .dataset_url == "https://www.ecmwf.int/en/forecasts/datasets/open-data" and
        .licence_id == "CC-BY-4.0"
      ' <<< "${manifest}" >/dev/null; then
      echo "Malformed or incomplete committed manifest: ${path}" >&2
      return 2
    fi
    committed_manifest="${manifest}"
    committed_remote_base="${destination}/${path%/manifest.json}"
    return 0
  done <<< "${listing}"
  return 1
}

discovery_json="${work_root}/discovery.json"
discover_args=(
  python -m src.ingestion.nwp_archiver discover
  --model "${model}"
  --mode "${profile}"
  --result-json "${discovery_json}"
)
if [[ -n "${issue_time_utc}" ]]; then
  discover_args+=(--issue-time-utc "${issue_time_utc}")
fi
"${discover_args[@]}"

source_name="$(jq -er '.nwp_source' "${discovery_json}")"
mapfile -t candidates < <(jq -er '.candidate_issue_times_utc[]' "${discovery_json}")
((${#candidates[@]} > 0)) || {
  echo "No ECMWF candidate cycles discovered" >&2; exit 1;
}

committed=()
for issue in "${candidates[@]}"; do
  issue_date="${issue:0:10}"
  issue_hour="${issue:11:2}"
  partition="nwp_source=${source_name}/issue_date=${issue_date}/issue_hour=${issue_hour}"
  if [[ "${profile}" == "smoke" ]]; then
    continue
  elif manifest_is_committed "${partition}" "${issue}" "${source_name}"; then
    committed+=("${issue}")
    summary_manifest "skipped" "${committed_manifest}" "${committed_remote_base}"
  else
    status=$?
    ((status == 1)) || exit "${status}"
  fi
done

candidates_json="${work_root}/candidate-list.json"
committed_json="${work_root}/committed-list.json"
selection_json="${work_root}/selection.json"
jq -c '.candidate_issue_times_utc' "${discovery_json}" > "${candidates_json}"
jq -cn '$ARGS.positional' --args "${committed[@]}" > "${committed_json}"
python -m src.ingestion.nwp_archiver select \
  --mode "${profile}" \
  --candidates-json "${candidates_json}" \
  --committed-json "${committed_json}" \
  --result-json "${selection_json}"
mapfile -t selected < <(jq -er '.selected_issue_times_utc[]' "${selection_json}")

if ((${#selected[@]} == 0)); then
  summary "- ${model}: no uncommitted cycles"
  exit 0
fi

archive_profile="full"
[[ "${profile}" == "smoke" ]] && archive_profile="smoke"

for issue in "${selected[@]}"; do
  current_issue="${issue}"
  safe_issue="${issue//[:\-]/}"
  result_json="${work_root}/archive-${model}-${safe_issue}.json"
  python -m src.ingestion.nwp_archiver archive \
    --site-config configs/site_plts-ikn.yaml \
    --model "${model}" \
    --profile "${archive_profile}" \
    --issue-time-utc "${issue}" \
    --work-root "${work_root}/grib-${model}-${safe_issue}" \
    --output-root "${output_root}" \
    --result-json "${result_json}"

  parquet_path="$(jq -er '.parquet_path' "${result_json}")"
  manifest_path="$(jq -er '.manifest_path' "${result_json}")"
  relative_path="$(jq -er '.relative_path' "${result_json}")"
  local_sha="$(jq -er '.manifest.parquet_sha256' "${result_json}")"
  remote_base="${destination}/${relative_path}"
  remote_parquet="${remote_base}/weather_forecast_raw.parquet"
  remote_manifest="${remote_base}/manifest.json"
  readback="${verify_root}/${model}-${safe_issue}.parquet"
  readback_manifest="${verify_root}/${model}-${safe_issue}.manifest.json"
  verified_json="${verify_root}/${model}-${safe_issue}.verified.json"

  rclone copyto "${parquet_path}" "${remote_parquet}" \
    --config "${RCLONE_CONFIG}" --immutable --retries 3
  rclone copyto "${remote_parquet}" "${readback}" \
    --config "${RCLONE_CONFIG}" --retries 3
  remote_sha="$(sha256sum "${readback}" | awk '{print $1}')"
  [[ "${remote_sha}" == "${local_sha}" ]] || {
    echo "Remote Parquet SHA-256 mismatch for ${model} ${issue}" >&2
    exit 1
  }
  rclone copyto "${manifest_path}" "${remote_manifest}" \
    --config "${RCLONE_CONFIG}" --immutable --retries 3
  rclone copyto "${remote_manifest}" "${readback_manifest}" \
    --config "${RCLONE_CONFIG}" --retries 3
  python -m src.ingestion.nwp_archiver verify \
    --manifest "${readback_manifest}" \
    --parquet "${readback}" \
    --expected-source "${source_name}" \
    --expected-model "${model}" \
    --expected-issue-time-utc "${issue}" \
    --result-json "${verified_json}"
  verified_manifest="$(jq -cer '.manifest' "${verified_json}")"
  [[ "$(jq -er '.parquet_sha256' <<< "${verified_manifest}")" == "${local_sha}" ]]
  summary_manifest "committed" "${verified_manifest}" "${remote_base}"
done
