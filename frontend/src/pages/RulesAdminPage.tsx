import { Navigate } from "react-router-dom";
import { useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listMarketRules, createMarketRule, deleteMarketRule,
  listRouteRules, createRouteRule, deleteRouteRule,
  seedMarketDefaults, syncRouteFromSheet,
  MarketRule, RouteRule,
} from "@/lib/api";
import { Plus, Trash2, RefreshCw, Database } from "lucide-react";

export default function RulesAdminPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const isAdmin = user?.role === "admin";
  const [tab, setTab] = useState<"market" | "route">("market");
  const [mMarket, setMMarket] = useState("");
  const [mKeyword, setMKeyword] = useState("");
  const [rMarket, setRMarket] = useState("");
  const [rRoute, setRRoute] = useState("");
  const [rKeywords, setRKeywords] = useState("");

  const { data: marketRules } = useQuery({ queryKey: ["market-rules"], queryFn: listMarketRules, enabled: isAdmin });
  const { data: routeRules } = useQuery({ queryKey: ["route-rules"], queryFn: listRouteRules, enabled: isAdmin });

  const addMarket = useMutation({
    mutationFn: () => createMarketRule({ market: mMarket, keyword: mKeyword }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["market-rules"] }); setMKeyword(""); },
  });
  const addRoute = useMutation({
    mutationFn: () => createRouteRule({ thi_truong: rMarket, tuyen_tour: rRoute, keywords: rKeywords }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["route-rules"] }); setRKeywords(""); },
  });
  const seedMarket = useMutation({ mutationFn: seedMarketDefaults, onSuccess: () => qc.invalidateQueries({ queryKey: ["market-rules"] }) });
  const syncRoute = useMutation({ mutationFn: syncRouteFromSheet, onSuccess: () => qc.invalidateQueries({ queryKey: ["route-rules"] }) });

  if (!isAdmin) return <Navigate to="/" replace />;

  return (
    <div className="p-6 max-w-5xl space-y-6">
      <div>
        <h1 className="text-xl font-bold">Quy tắc phân loại</h1>
        <p className="text-sm text-gray-500">Quản lý keyword Thị trường và Tuyến tour (thay hardcode)</p>
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
            <button onClick={() => seedMarket.mutate()} className="btn-secondary text-sm"><Database size={14} /> Import mặc định</button>
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
                      <button className="text-red-500" onClick={() => deleteMarketRule(r.id).then(() => qc.invalidateQueries({ queryKey: ["market-rules"] }))}>
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-gray-400 p-3">{(marketRules ?? []).length} rules — keyword dài được ưu tiên trước</p>
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
            <div className="flex gap-2">
              <button onClick={() => addRoute.mutate()} disabled={!rMarket || !rRoute || !rKeywords} className="btn-primary text-sm"><Plus size={14} /> Thêm rule</button>
              <button onClick={() => syncRoute.mutate()} className="btn-secondary text-sm"><RefreshCw size={14} /> Sync từ Google Sheet</button>
            </div>
            <p className="text-xs text-gray-500">VD: Thị trường=Thái Lan, Tuyến=Bangkok-Pattaya, Keywords=bangkok,pattaya</p>
          </div>
          <div className="card overflow-auto max-h-[500px]">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0"><tr>
                <th className="px-3 py-2 text-left">Thị trường</th><th className="px-3 py-2 text-left">Tuyến</th><th className="px-3 py-2 text-left">Keywords</th><th></th>
              </tr></thead>
              <tbody>
                {(routeRules ?? []).slice(0, 200).map((r: RouteRule) => (
                  <tr key={r.id} className="border-t">
                    <td className="px-3 py-2">{r.thi_truong}</td>
                    <td className="px-3 py-2">{r.tuyen_tour}</td>
                    <td className="px-3 py-2 font-mono text-xs">{r.keywords}</td>
                    <td className="px-3 py-2">
                      <button className="text-red-500" onClick={() => deleteRouteRule(r.id).then(() => qc.invalidateQueries({ queryKey: ["route-rules"] }))}>
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
