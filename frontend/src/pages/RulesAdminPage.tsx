import { Navigate } from "react-router-dom";
import { useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listMarketRules, createMarketRule, deleteMarketRule,
  listRouteRules, createRouteRule, deleteRouteRule,
  listCompanyRules, createCompanyRule, deleteCompanyRule,
  listDepartureRules, createDepartureRule, deleteDepartureRule,
  seedMarketDefaults, seedCompanyDefaults, seedDepartureDefaults,
  applyCompanyRulesToTours, applyDepartureRulesToTours, applyClassificationToTours,
  syncRouteFromSheet, syncRouteToSheet,
  syncMarketFromSheet, syncMarketToSheet,
  syncAllFromSheet, syncAllToSheet,
  MarketRule, RouteRule, CompanyRule, DepartureRule,
} from "@/lib/api";
import { COL } from "@/lib/glossary";
import { InfoTip } from "@/components/InfoTip";
import { Plus, Trash2, RefreshCw, Database, Upload, Download, ArrowLeftRight } from "lucide-react";

export default function RulesAdminPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const isAdmin = user?.role === "admin";
  const [tab, setTab] = useState<"market" | "route" | "company" | "departure">("market");
  const [syncMsg, setSyncMsg] = useState("");
  const [mMarket, setMMarket] = useState("");
  const [mKeyword, setMKeyword] = useState("");
  const [rMarket, setRMarket] = useState("");
  const [rRoute, setRRoute] = useState("");
  const [rKeywords, setRKeywords] = useState("");
  const [cCanonical, setCCanonical] = useState("");
  const [cAlias, setCAlias] = useState("");
  const [dCanonical, setDCanonical] = useState("");
  const [dAlias, setDAlias] = useState("");

  const { data: marketRules } = useQuery({ queryKey: ["market-rules"], queryFn: listMarketRules, enabled: isAdmin });
  const { data: routeRules } = useQuery({ queryKey: ["route-rules"], queryFn: listRouteRules, enabled: isAdmin });
  const { data: companyRules } = useQuery({ queryKey: ["company-rules"], queryFn: listCompanyRules, enabled: isAdmin });
  const { data: departureRules } = useQuery({ queryKey: ["departure-rules"], queryFn: listDepartureRules, enabled: isAdmin });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["market-rules"] });
    qc.invalidateQueries({ queryKey: ["route-rules"] });
    qc.invalidateQueries({ queryKey: ["company-rules"] });
    qc.invalidateQueries({ queryKey: ["departure-rules"] });
  };

  const onSync = (fn: () => Promise<{ message?: string }>, label: string) =>
    fn().then((r) => { setSyncMsg(r.message || label); invalidate(); }).catch((e) => setSyncMsg(String(e.response?.data?.detail || e.message)));

  const addMarket = useMutation({
    mutationFn: () => createMarketRule({ market: mMarket, keyword: mKeyword }),
    onSuccess: () => { invalidate(); setMKeyword(""); setSyncMsg("Đã lưu DB và tự động ghi lên Sheet (nếu có quyền)"); },
  });
  const addRoute = useMutation({
    mutationFn: () => createRouteRule({ thi_truong: rMarket, tuyen_tour: rRoute, keywords: rKeywords }),
    onSuccess: () => { invalidate(); setRKeywords(""); setSyncMsg("Đã lưu DB và tự động ghi lên Sheet 'Điểm tuyến Tour'"); },
  });
  const addCompany = useMutation({
    mutationFn: () => createCompanyRule({ canonical_name: cCanonical, alias: cAlias }),
    onSuccess: () => { invalidate(); setCAlias(""); setSyncMsg("Đã thêm alias công ty"); },
  });
  const addDeparture = useMutation({
    mutationFn: () => createDepartureRule({ canonical_name: dCanonical, alias: dAlias }),
    onSuccess: () => { invalidate(); setDAlias(""); setSyncMsg("Đã thêm alias điểm khởi hành"); },
  });

  if (!isAdmin) return <Navigate to="/" replace />;

  return (
    <div className="p-6 max-w-5xl space-y-6">
      <div>
        <h1 className="text-xl font-bold">Quy tắc phân loại</h1>
        <p className="text-sm text-gray-500">Đồng bộ 2 chiều với Google Sheet — sửa trên app sẽ ghi ngược lên Sheet</p>
      </div>

      {/* Global sync bar */}
      <div className="card p-4 space-y-3 bg-slate-50">
        <p className="text-sm font-medium flex items-center gap-2"><ArrowLeftRight size={16} /> Đồng bộ Google Sheet</p>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => onSync(syncAllFromSheet, "OK")} className="btn-secondary text-xs flex items-center gap-1">
            <Download size={13} /> Kéo tất cả Sheet → App
          </button>
          <button onClick={() => onSync(syncAllToSheet, "OK")} className="btn-secondary text-xs flex items-center gap-1">
            <Upload size={13} /> Đẩy tất cả App → Sheet
          </button>
          <button onClick={() => onSync(applyClassificationToTours, "Đã áp dụng phân loại lên toàn bộ tour")} className="btn-primary text-xs flex items-center gap-1">
            <RefreshCw size={13} /> Áp dụng phân loại → tour
          </button>
        </div>
        <p className="text-xs text-gray-500">
          Tuyến tour: tab <strong>Điểm tuyến Tour</strong> · Thị trường: tab <strong>Quy tắc Thị trường</strong> (tự tạo nếu chưa có)
        </p>
        {syncMsg && <p className="text-xs text-green-700 bg-green-50 px-3 py-2 rounded">{syncMsg}</p>}
      </div>

      <div className="flex gap-2 flex-wrap">
        {([
          ["market", "Thị trường"],
          ["route", "Tuyến tour"],
          ["company", COL.congTy],
          ["departure", COL.diemKhoiHanh],
        ] as const).map(([t, label]) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-lg text-sm font-medium ${tab === t ? "bg-primary-600 text-white" : "bg-gray-100"}`}>
            {label}
          </button>
        ))}
      </div>

      {tab === "market" && (
        <div className="space-y-4">
          <div className="card p-4 flex flex-wrap gap-2 items-end">
            <div><label className="text-xs text-gray-500">Thị trường</label>
              <input className="input text-sm" value={mMarket} onChange={(e) => setMMarket(e.target.value)} placeholder="Thái Lan" /></div>
            <div className="flex-1 min-w-[200px]"><label className="text-xs text-gray-500">Keyword</label>
              <input className="input text-sm" value={mKeyword} onChange={(e) => setMKeyword(e.target.value)} placeholder="bangkok, pattaya..." /></div>
            <button onClick={() => addMarket.mutate()} disabled={!mMarket || !mKeyword} className="btn-primary text-sm"><Plus size={14} /> Thêm</button>
            <button onClick={() => onSync(seedMarketDefaults, "Import xong")} className="btn-secondary text-sm"><Database size={14} /> Import mặc định</button>
            <button onClick={() => onSync(syncMarketFromSheet, "OK")} className="btn-secondary text-sm"><Download size={14} /> Sheet → App</button>
            <button onClick={() => onSync(syncMarketToSheet, "OK")} className="btn-secondary text-sm"><Upload size={14} /> App → Sheet</button>
          </div>
          <div className="card overflow-auto max-h-[500px]">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0"><tr>
                <th className="px-3 py-2 text-left">Thị trường</th><th className="px-3 py-2 text-left">Keyword</th><th></th>
              </tr></thead>
              <tbody>
                {(marketRules ?? []).map((r: MarketRule) => (
                  <tr key={r.id} className="border-t">
                    <td className="px-3 py-2">{r.market}</td>
                    <td className="px-3 py-2 font-mono text-xs">{r.keyword}</td>
                    <td className="px-3 py-2">
                      <button className="text-red-500" onClick={() => deleteMarketRule(r.id).then(() => { invalidate(); setSyncMsg("Đã xóa và cập nhật Sheet"); })}>
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-gray-400 p-3">{(marketRules ?? []).length} rules — xóa/thêm tự động ghi Sheet</p>
          </div>
        </div>
      )}

      {tab === "route" && (
        <div className="space-y-4">
          <div className="card p-4 space-y-2">
            <div className="grid grid-cols-3 gap-2">
              <input className="input text-sm" placeholder="Thị trường" value={rMarket} onChange={(e) => setRMarket(e.target.value)} />
              <input className="input text-sm" placeholder="Tuyến tour (tên hiển thị)" value={rRoute} onChange={(e) => setRRoute(e.target.value)} />
              <input className="input text-sm" placeholder="Keywords (cách nhau dấu phẩy, AND)" value={rKeywords} onChange={(e) => setRKeywords(e.target.value)} />
            </div>
            <div className="flex flex-wrap gap-2">
              <button onClick={() => addRoute.mutate()} disabled={!rMarket || !rRoute || !rKeywords} className="btn-primary text-sm"><Plus size={14} /> Thêm rule</button>
              <button onClick={() => onSync(syncRouteFromSheet, "OK")} className="btn-secondary text-sm"><Download size={14} /> Sheet → App</button>
              <button onClick={() => onSync(syncRouteToSheet, "OK")} className="btn-secondary text-sm"><Upload size={14} /> App → Sheet</button>
            </div>
          </div>
          <div className="card overflow-auto max-h-[500px]">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0"><tr>
                <th className="px-3 py-2 text-left">Thị trường</th><th className="px-3 py-2 text-left">Tuyến</th><th className="px-3 py-2 text-left">Keywords</th><th></th>
              </tr></thead>
              <tbody>
                {(routeRules ?? []).slice(0, 300).map((r: RouteRule) => (
                  <tr key={r.id} className="border-t">
                    <td className="px-3 py-2">{r.thi_truong}</td>
                    <td className="px-3 py-2">{r.tuyen_tour}</td>
                    <td className="px-3 py-2 font-mono text-xs">{r.keywords}</td>
                    <td className="px-3 py-2">
                      <button className="text-red-500" onClick={() => deleteRouteRule(r.id).then(() => { invalidate(); setSyncMsg("Đã xóa và cập nhật Sheet"); })}>
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "company" && (
        <div className="space-y-4">
          <div className="card p-4 flex flex-wrap gap-2 items-end">
            <div><label className="text-xs text-gray-500">Tên chính thức</label>
              <input className="input text-sm" value={cCanonical} onChange={(e) => setCCanonical(e.target.value)} placeholder="Vietravel" /></div>
            <div className="flex-1 min-w-[200px]"><label className="text-xs text-gray-500">Alias (tên từ nguồn khác)</label>
              <input className="input text-sm" value={cAlias} onChange={(e) => setCAlias(e.target.value)} placeholder="vietravel, vtr, viet travel..." /></div>
            <button onClick={() => addCompany.mutate()} disabled={!cCanonical || !cAlias} className="btn-primary text-sm"><Plus size={14} /> Thêm</button>
            <button onClick={() => onSync(seedCompanyDefaults, "Import xong")} className="btn-secondary text-sm"><Database size={14} /> Alias mặc định</button>
            <button onClick={() => onSync(applyCompanyRulesToTours, "OK")} className="btn-secondary text-sm"><RefreshCw size={14} /> Áp dụng lại toàn bộ tour</button>
          </div>
          <p className="text-xs text-gray-500 inline-flex items-center gap-1">
            Chuẩn hóa tên công ty từ nhiều nguồn.
            <InfoTip text="Alias khớp không phân biệt hoa thường; alias dài được ưu tiên. Bấm 'Áp dụng lại' để cập nhật toàn bộ tour hiện có." />
          </p>
          <div className="card overflow-auto max-h-[500px]">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0"><tr>
                <th className="px-3 py-2 text-left">Tên chính thức</th><th className="px-3 py-2 text-left">Alias</th><th></th>
              </tr></thead>
              <tbody>
                {(companyRules ?? []).map((r: CompanyRule) => (
                  <tr key={r.id} className="border-t">
                    <td className="px-3 py-2 font-medium">{r.canonical_name}</td>
                    <td className="px-3 py-2 font-mono text-xs">{r.alias}</td>
                    <td className="px-3 py-2">
                      <button className="text-red-500" onClick={() => deleteCompanyRule(r.id).then(() => { invalidate(); setSyncMsg("Đã xóa alias"); })}>
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-gray-400 p-3">{(companyRules ?? []).length} alias rules</p>
          </div>
        </div>
      )}

      {tab === "departure" && (
        <div className="space-y-4">
          <div className="card p-4 flex flex-wrap gap-2 items-end">
            <div><label className="text-xs text-gray-500">Tên chính thức</label>
              <input className="input text-sm" value={dCanonical} onChange={(e) => setDCanonical(e.target.value)} placeholder="TP.HCM" /></div>
            <div className="flex-1 min-w-[200px]"><label className="text-xs text-gray-500">Alias (từ nguồn khác)</label>
              <input className="input text-sm" value={dAlias} onChange={(e) => setDAlias(e.target.value)} placeholder="sài gòn, hcm, tphcm..." /></div>
            <button onClick={() => addDeparture.mutate()} disabled={!dCanonical || !dAlias} className="btn-primary text-sm"><Plus size={14} /> Thêm</button>
            <button onClick={() => onSync(seedDepartureDefaults, "Import xong")} className="btn-secondary text-sm"><Database size={14} /> Alias mặc định</button>
            <button onClick={() => onSync(applyDepartureRulesToTours, "OK")} className="btn-secondary text-sm"><RefreshCw size={14} /> Áp dụng lại toàn bộ tour</button>
          </div>
          <p className="text-xs text-gray-500 inline-flex items-center gap-1">
            Chuẩn hóa {COL.diemKhoiHanh} — ví dụ Sài Gòn / HCM / TPHCM → TP.HCM.
            <InfoTip text="Dùng khi so sánh Vietravel cùng điểm khởi hành. Nếu có nhiều điểm (cách nhau dấu phẩy), hệ thống thử khớp cả chuỗi và phần đầu tiên." />
          </p>
          <div className="card overflow-auto max-h-[500px]">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0"><tr>
                <th className="px-3 py-2 text-left">Tên chính thức</th><th className="px-3 py-2 text-left">Alias</th><th></th>
              </tr></thead>
              <tbody>
                {(departureRules ?? []).map((r: DepartureRule) => (
                  <tr key={r.id} className="border-t">
                    <td className="px-3 py-2 font-medium">{r.canonical_name}</td>
                    <td className="px-3 py-2 font-mono text-xs">{r.alias}</td>
                    <td className="px-3 py-2">
                      <button className="text-red-500" onClick={() => deleteDepartureRule(r.id).then(() => { invalidate(); setSyncMsg("Đã xóa alias điểm KH"); })}>
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-gray-400 p-3">{(departureRules ?? []).length} alias rules</p>
          </div>
        </div>
      )}
    </div>
  );
}
