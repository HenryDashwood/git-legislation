import type { Json } from "../api";

export function ProvisionsPartial(props: { versionId: string; provisions: Json[]; error: string | null }) {
  return (
    <>
      <h2>Provisions</h2>
      {props.error !== null ? (
        <div class="notice error">Could not load provisions: {props.error}</div>
      ) : props.provisions.length > 0 ? (
        <ol class="compact-list">
          {props.provisions.map((provision) => (
            <li>
              <strong>{provision["number"] ?? provision["ordinal"]}</strong> {provision["heading"]}{" "}
              <span class="metadata">{provision["anchor"]}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p>No provisions found for {props.versionId}.</p>
      )}
    </>
  );
}

export function FilesPartial(props: { versionId: string; files: Json[]; error: string | null }) {
  return (
    <>
      <h2>Files</h2>
      {props.error !== null ? (
        <div class="notice error">Could not load files: {props.error}</div>
      ) : props.files.length > 0 ? (
        <ul class="compact-list">
          {props.files.map((file) => (
            <li>
              <strong>{file["file_kind"]}</strong>{" "}
              {file["is_canonical"] ? <span class="version-chip">canonical</span> : null}
              {file["object_key"] ? (
                <div class="metadata">{file["object_key"]}</div>
              ) : file["source_url"] ? (
                <div class="metadata">
                  <a href={String(file["source_url"])}>{file["source_url"]}</a>
                </div>
              ) : null}
              {file["content_type"] || file["byte_size"] ? (
                <div class="metadata">
                  {file["content_type"] ?? "unknown type"}
                  {file["byte_size"] ? <> &middot; {file["byte_size"]} bytes</> : null}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p>No files found for {props.versionId}.</p>
      )}
    </>
  );
}

export function ContentPartial(props: { versionId: string; content: string; error: string | null }) {
  return (
    <>
      <h2>Content</h2>
      {props.error !== null ? (
        <div class="notice error">Could not load content: {props.error}</div>
      ) : props.content !== "" ? (
        <pre class="content-block">{props.content}</pre>
      ) : (
        <p>No content found for {props.versionId}.</p>
      )}
    </>
  );
}
