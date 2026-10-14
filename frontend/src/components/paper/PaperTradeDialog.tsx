import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, X } from "lucide-react";
import { ApiError, api, type PaperPreview } from "@/lib/api";

interface PaperTradeDialogProps {
  mode: "buy" | "sell";
  symbol: string;
  name?: string | null;
  sellableQty?: number;
  onClose: () => void;
  onDone: () => void;
}

const PREVIEW_DEBOUNCE_MS = 350;
const LOT_SIZE = 100;

export function fmtMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  return v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  return `${(v * 100).toFixed(2)}%`;
}

/** Buy (watchlist) / sell (paper positions) dialog with live fee trial. */
export function PaperTradeDialog({
  mode,
  symbol,
  name,
  sellableQty,
  onClose,
  onDone,
}: PaperTradeDialogProps) {
  const { t } = useTranslation();
  const [qty, setQty] = useState(LOT_SIZE);
  const [preview, setPreview] = useState<PaperPreview | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  const maxQty = mode === "sell" ? sellableQty ?? 0 : undefined;
  const qtyValid =
    Number.isInteger(qty) && qty > 0 && qty % LOT_SIZE === 0 &&
    (maxQty === undefined || qty <= maxQty);

  useEffect(() => {
    const requestQty = qtyValid ? qty : null;
    const current = ++seq.current;
    setError(null);
    setLoadingPreview(true);
    const timer = setTimeout(async () => {
      try {
        const p = await api.paperPreview(symbol, requestQty, mode);
        if (current === seq.current) setPreview(p);
      } catch (err) {
        if (current === seq.current) {
          setPreview(null);
          setError(err instanceof ApiError ? err.message : t("paper.dialog.previewFailed"));
        }
      } finally {
        if (current === seq.current) setLoadingPreview(false);
      }
    }, PREVIEW_DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, qty, mode]);

  const submit = async () => {
    if (!qtyValid || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      if (mode === "buy") await api.paperBuy(symbol, qty);
      else await api.paperSell(symbol, qty);
      onDone();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("paper.dialog.submitFailed"));
      setSubmitting(false);
    }
  };

  const sessionLabel = preview?.price_session === "live"
    ? t("paper.session.live")
    : t("paper.session.close");

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-24"
      role="dialog"
      aria-modal="true"
      aria-label={t(mode === "buy" ? "paper.dialog.buyTitle" : "paper.dialog.sellTitle")}
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-lg border border-border bg-background p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold">
            {t(mode === "buy" ? "paper.dialog.buyTitle" : "paper.dialog.sellTitle")}
          </h2>
          <button type="button" aria-label={t("paper.dialog.close")} onClick={onClose}>
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        <div className="mb-3 text-sm">
          <div className="font-medium">{name || symbol}</div>
          <div className="text-xs text-muted-foreground">{symbol}</div>
        </div>

        <div className="mb-3 rounded-md border border-border/60 bg-muted/30 p-3 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">{t("paper.dialog.price")}</span>
            <span>
              {loadingPreview || !preview ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              ) : (
                <>
                  <span className="font-semibold">{fmtMoney(preview.price)}</span>
                  <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
                    {sessionLabel} · {preview.price_trade_date}
                  </span>
                </>
              )}
            </span>
          </div>
        </div>

        <label className="mb-1 block text-sm text-muted-foreground">
          {t("paper.dialog.qty")}
        </label>
        <input
          autoFocus
          type="number"
          min={LOT_SIZE}
          step={LOT_SIZE}
          value={qty}
          onChange={(e) => setQty(Number(e.target.value))}
          className="mb-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
        />
        {mode === "sell" && (
          <div className="mb-2 text-xs text-muted-foreground">
            {t("paper.dialog.sellable", { n: sellableQty ?? 0 })}
          </div>
        )}
        {!qtyValid && (
          <div className="mb-2 text-xs text-red-500">{t("paper.dialog.qtyInvalid")}</div>
        )}

        {preview?.chanlun && (
          <div className="mb-3 rounded-md border border-border/60 bg-muted/30 p-3 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">{t("paper.dialog.chanlun")}</span>
              <span className="font-semibold">
                {preview.chanlun.score === null
                  ? t("paper.dialog.noChanlun")
                  : `${preview.chanlun.score} / 5`}
              </span>
            </div>
            {preview.chanlun.dim7_chanlun_score && (
              <div className="mt-1 line-clamp-2 text-muted-foreground">
                {preview.chanlun.dim7_chanlun_score}
              </div>
            )}
          </div>
        )}
        {preview && !preview.chanlun && (
          <div className="mb-3 rounded-md border border-border/60 bg-muted/30 p-3 text-xs text-muted-foreground">
            {t("paper.dialog.noChanlun")}
          </div>
        )}

        {preview && qtyValid && (
          <dl className="mb-3 space-y-1 text-sm">
            <div className="flex justify-between">
              <dt className="text-muted-foreground">{t("paper.dialog.amount")}</dt>
              <dd>{fmtMoney(preview.amount)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted-foreground">{t("paper.dialog.commission")}</dt>
              <dd>{fmtMoney(preview.commission)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted-foreground">{t("paper.dialog.stampTax")}</dt>
              <dd>{fmtMoney(preview.stamp_tax)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted-foreground">{t("paper.dialog.transferFee")}</dt>
              <dd>{fmtMoney(preview.transfer_fee)}</dd>
            </div>
            <div className="flex justify-between border-t border-border/60 pt-1 font-medium">
              <dt>{mode === "buy" ? t("paper.dialog.totalCost") : t("paper.dialog.netProceeds")}</dt>
              <dd>
                {fmtMoney(mode === "buy" ? preview.total_cost : preview.net_proceeds)}
              </dd>
            </div>
          </dl>
        )}

        {mode === "sell" && (
          <p className="mb-3 text-xs text-muted-foreground">{t("paper.dialog.t1Hint")}</p>
        )}

        {error && <p role="alert" className="mb-3 text-sm text-red-500">{error}</p>}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted/60"
            onClick={onClose}
          >
            {t("paper.dialog.cancel")}
          </button>
          <button
            type="button"
            disabled={!qtyValid || submitting || loadingPreview || !preview}
            className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:opacity-90 disabled:opacity-50"
            onClick={() => void submit()}
          >
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : mode === "buy" ? (
              t("paper.dialog.confirmBuy")
            ) : (
              t("paper.dialog.confirmSell")
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
