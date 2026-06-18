import { useRef } from "react";
import { Editor } from "@tinymce/tinymce-react";

// Self-host TinyMCE (GPL, miễn phí) — bundle, KHÔNG dùng CDN/API key.
import "tinymce/tinymce";
import "tinymce/models/dom/model";
import "tinymce/themes/silver";
import "tinymce/icons/default";
import "tinymce/skins/ui/oxide/skin.min.css";
import "tinymce/plugins/table";
import "tinymce/plugins/lists";
import "tinymce/plugins/advlist";
import "tinymce/plugins/link";
import "tinymce/plugins/code";
import "tinymce/plugins/searchreplace";

function splitDoc(html: string): { head: string; body: string } {
  try {
    const doc = new DOMParser().parseFromString(html, "text/html");
    return { head: doc.head?.innerHTML || "", body: doc.body?.innerHTML || html };
  } catch {
    return { head: "", body: html };
  }
}

// Lấy CSS trong <style> của head → nhồi vào content_style để editor giữ đúng giao diện report.
function extractCss(headHtml: string): string {
  const m = headHtml.match(/<style[^>]*>([\s\S]*?)<\/style>/gi);
  if (!m) return "";
  return m.map((s) => s.replace(/<\/?style[^>]*>/gi, "")).join("\n");
}

export default function ReportEditor({
  html,
  onSave,
  onCancel,
  saving,
}: {
  html: string;
  onSave: (fullHtml: string) => void;
  onCancel: () => void;
  saving?: boolean;
}) {
  const { head, body } = splitDoc(html);
  const contentRef = useRef(body);
  const css = extractCss(head);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="btn-primary text-xs"
          disabled={saving}
          onClick={() => onSave(`<!DOCTYPE html><html><head>${head}</head><body>${contentRef.current}</body></html>`)}
        >
          {saving ? "Đang lưu…" : "💾 Lưu vào hệ thống"}
        </button>
        <button type="button" className="btn-secondary text-xs" onClick={onCancel} disabled={saving}>Huỷ</button>
        <span className="text-xs text-gray-400">Sửa chữ, bảng (kéo cột, thêm/xoá hàng), màu… như Word. Lưu xong giữ tới lần Làm mới / snapshot ngày.</span>
      </div>
      <Editor
        licenseKey="gpl"
        initialValue={body}
        onEditorChange={(c) => { contentRef.current = c; }}
        init={{
          height: 760,
          menubar: "edit insert format table",
          plugins: "table lists advlist link code searchreplace",
          toolbar:
            "undo redo | bold italic underline | forecolor backcolor | fontsize | "
            + "alignleft aligncenter alignright | bullist numlist | table | link | removeformat | searchreplace | code",
          skin: false,
          content_css: false,
          content_style: css,
          branding: false,
          promotion: false,
          table_toolbar:
            "tableprops tabledelete | tableinsertrowbefore tableinsertrowafter tabledeleterow | "
            + "tableinsertcolbefore tableinsertcolafter tabledeletecol",
        }}
      />
    </div>
  );
}
