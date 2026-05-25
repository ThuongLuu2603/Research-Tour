import { Navigate } from "react-router-dom";
import { useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listMarketRules, createMarketRule, deleteMarketRule,
  listRouteRules, createRouteRule, deleteRouteRule,
  seedMarketDefaults,
  syncRouteFromSheet, syncRouteToSheet,
  syncMarketFromSheet, syncMarketToSheet,
  syncAllFromSheet, syncAllToSheet,
  MarketRule, RouteRule,
} from "@/lib/api";
import { Plus, Trash2, RefreshCw, Database, Upload, Download, ArrowLeftRight } from "lucide-react";

export default function RulesAdminPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const isAdmin = user?.role === "admin";
  const [tab, setTab] = useState<"market" | "route">("market");
  const [syncMsg, setSyncMsg] = useState("");
  const [mMarket, setMMarket] = useState("");
  const [mKeyword, setMKeyword] = useState("");
  const [rMarket, setRMarket] = useState("");
  const [rRoute, setRRoute] = useState("");
  const [rKeywords, setRKeywords] = useState("");

  const { data: marketRules } = useQuery({ queryKey: ["market-rules"], queryFn: listMarketRules, enabled: isAdmin });
  const { data: routeRules } = useQuery({ queryKey: ["route-rules"], queryFn: listRouteRules, enabled: isAdmin });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["market-rules"] });
    qc.invalidateQueries({ queryKey: ["route-rules"] });
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
        </div>
        <p className="text-xs text-gray-500">
          Tuyến tour: tab <strong>Điểm tuyến Tour</strong> · Thị trường: tab <strong>Quy tắc Thị trường</strong> (tự tạo nếu chưa có)
        </p>
        {syncMsg && <p className="text-xs text-green-700 bg-green-50 px-3 py-2 rounded">{syncMsg}</p>}
      </div>

      <div className="flex gap-2">
        {(["market", "route"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-lg text-sm font-medium ${tab === t ? "bg-primary-600 text-white" : "bg-gray-100"}`}>
            {t === "market" ? "Thị trường" : "Tuyến tour"}
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
    </div>
  );
}
