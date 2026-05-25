import { Navigate, useSearchParams } from "react-router-dom";

/** Trang Đối thủ cũ — chuyển sang Trung tâm So sánh tab Đối thủ */
export default function Competitor() {
  const [params] = useSearchParams();
  const q = params.toString();
  return <Navigate to={`/compare?tab=competitors${q ? "&" + q : ""}`} replace />;
}
