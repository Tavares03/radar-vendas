"use client";

import { BriefcaseBusiness, QrCode, RefreshCw, Smartphone, TriangleAlert, Unplug } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";

import { Button, Empty, ErrorNote, Initials, Loading, PageTitle, Panel } from "@/components/ui";
import { api, type Schemas, unwrap, unwrapEmpty } from "@/lib/api/client";
import { useWhatsApp } from "@/lib/api/hooks";
import { formatDateTime } from "@/lib/format";

type SellerRow = Schemas["WhatsAppSellerOut"];
type Qr = Schemas["WhatsAppQrOut"];

/** O QR code do WhatsApp expira em ~20 s: um novo é pedido antes disso. */
const QR_REFRESH_MS = 18_000;

const STATE: Record<string, { label: string; chip: string }> = {
  conectado: { label: "Conectado", chip: "bg-ok-marca text-ok" },
  aguardando_qr: { label: "Esperando o QR code", chip: "bg-atencao-marca text-atencao" },
  desconectado: { label: "Desconectado", chip: "bg-critico-marca text-critico" },
};

/** O aviso que todo mundo vê antes de conectar: número de trabalho, de preferência Business. */
function Recommendation({ idleMinutes }: { idleMinutes: number }) {
  return (
    <Panel aria-labelledby="recomendacao" className="mb-6 border-l-4 border-l-sinal p-5">
      <h2 id="recomendacao" className="flex items-center gap-2 font-bold">
        <BriefcaseBusiness aria-hidden size={18} className="text-sinal-forte" />
        Recomendado: WhatsApp Business, com um número só de trabalho
      </h2>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-relaxed text-tinta-suave">
        <li>
          <strong>Tudo o que chega no número conectado entra no Radar</strong>, inclusive conversas
          pessoais, se o número também for usado para isso. Grupos ficam de fora.
        </li>
        <li>
          Se uma conversa pessoal entrar, o vendedor <strong>pede a remoção</strong> na própria conversa e a
          gestão aprova. O vendedor não apaga sozinho.
        </li>
        <li>
          Só entram as mensagens a partir da conexão. O histórico antigo continua entrando pelo export, em
          Conversas.
        </li>
        <li>
          Cada conversa é analisada depois de {idleMinutes} minutos sem mensagens novas. O texto aparece
          mascarado no painel em segundos.
        </li>
        <li>
          O Radar só lê: não envia mensagens nem marca nada como lido. A conexão usa o mesmo caminho do
          WhatsApp Web, por um conector que não é oficial do WhatsApp, e o número pode ser bloqueado.
        </li>
      </ul>
    </Panel>
  );
}

function StateTag({ state }: { state: string }) {
  const style = STATE[state] ?? { label: state, chip: "bg-linha text-grafite" };
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-bold whitespace-nowrap ${style.chip}`}>
      {style.label}
    </span>
  );
}

function QrPanel({ row, onClose }: { row: SellerRow; onClose: () => void }) {
  const sellerId = row.seller.id;
  // Pedir o QR é idempotente (cria a conexão na primeira vez); o SWR renova antes de expirar.
  const { data: qr, error: failure, mutate } = useSWR<Qr>(
    ["whatsapp-qr", sellerId],
    () =>
      unwrap(
        api.POST("/api/v1/whatsapp/sellers/{seller_id}/connect", { params: { path: { seller_id: sellerId } } }),
      ),
    { refreshInterval: QR_REFRESH_MS, revalidateOnFocus: false, shouldRetryOnError: false },
  );
  const error = failure ? (failure instanceof Error ? failure.message : "Não foi possível gerar o QR code.") : null;

  return (
    <div className="mt-4 grid gap-5 rounded-lg bg-papel/70 p-4 sm:grid-cols-[14rem_minmax(0,1fr)]">
      <div className="flex min-h-56 items-center justify-center rounded-lg border border-linha bg-white p-2">
        {qr?.qr_image ? (
          // eslint-disable-next-line @next/next/no-img-element -- QR em data URL, gerado na hora
          <img src={qr.qr_image} alt={`QR code para conectar o WhatsApp de ${row.seller.display_name}`} className="size-52" />
        ) : (
          <QrCode aria-hidden size={48} className="animate-pulse text-grafite" />
        )}
      </div>
      <div className="text-sm leading-relaxed">
        <p className="font-bold">No celular de {row.seller.display_name}:</p>
        <ol className="mt-1 list-decimal space-y-0.5 pl-5">
          <li>Abra o WhatsApp Business (ou o WhatsApp).</li>
          <li>
            Toque em <strong>⋮</strong> (Android) ou em <strong>Configurações</strong> (iPhone).
          </li>
          <li>
            Toque em <strong>Aparelhos conectados</strong> e depois em <strong>Conectar um aparelho</strong>.
          </li>
          <li>Aponte a câmera para o QR code ao lado.</li>
        </ol>
        {qr?.pairing_code ? (
          <p className="mt-2">
            Ou conecte com o número de telefone usando o código{" "}
            <strong className="numeros tracking-widest">{qr.pairing_code}</strong>.
          </p>
        ) : null}
        <p className="mt-2 text-xs text-grafite">O QR code muda a cada poucos segundos; esta tela acompanha sozinha.</p>
        {error ? (
          <p role="alert" className="mt-2 font-medium text-critico">
            {error}
          </p>
        ) : null}
        <div className="mt-3 flex gap-2">
          <Button onClick={() => void mutate()}>
            <RefreshCw aria-hidden size={15} /> Novo QR code
          </Button>
          <Button variant="quiet" onClick={onClose}>
            Fechar
          </Button>
        </div>
      </div>
    </div>
  );
}

function SellerCard({
  row,
  canManage,
  open,
  onOpen,
  onClose,
  onChanged,
}: {
  row: SellerRow;
  canManage: boolean;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  onChanged: () => void;
}) {
  const connection = row.connection;
  const state = connection?.state ?? "desconectado";
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function disconnect() {
    const ok = window.confirm(
      `Desconectar o WhatsApp de ${row.seller.display_name}? As conversas já recebidas continuam no Radar; as novas deixam de chegar.`,
    );
    if (!ok) return;
    setPending(true);
    setError(null);
    try {
      await unwrapEmpty(
        api.DELETE("/api/v1/whatsapp/sellers/{seller_id}/connection", {
          params: { path: { seller_id: row.seller.id } },
        }),
      );
      onChanged();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Não foi possível desconectar.");
    } finally {
      setPending(false);
    }
  }

  return (
    <li className="px-5 py-4">
      <div className="flex flex-wrap items-center gap-3">
        <Initials name={row.seller.display_name} />
        <div className="min-w-0 flex-1">
          <p className="font-semibold">{row.seller.display_name}</p>
          <p className="text-xs text-grafite">
            {state === "conectado" && connection?.connected_at
              ? `Conectado desde ${formatDateTime(connection.connected_at)}`
              : state === "desconectado" && connection?.disconnected_at
                ? `Saiu do ar em ${formatDateTime(connection.disconnected_at)}`
                : connection
                  ? "Ainda não terminou de conectar"
                  : "Nunca conectado"}
            {connection?.phone_tail ? `, número final ${connection.phone_tail}` : ""}
          </p>
        </div>
        <StateTag state={state} />
        <div className="flex gap-2">
          {state !== "conectado" && !open ? (
            <Button variant="primary" onClick={onOpen}>
              <Smartphone aria-hidden size={15} /> {connection ? "Reconectar" : "Conectar"}
            </Button>
          ) : null}
          {canManage && connection && state !== "desconectado" ? (
            <Button variant="danger" onClick={disconnect} disabled={pending}>
              <Unplug aria-hidden size={15} /> Desconectar
            </Button>
          ) : null}
        </div>
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-sm font-medium text-critico">
          {error}
        </p>
      ) : null}
      {open && state !== "conectado" ? <QrPanel row={row} onClose={onClose} /> : null}
      {open && state === "conectado" ? (
        <p role="status" className="mt-3 rounded-lg bg-ok-marca px-3 py-2 text-sm font-medium text-ok">
          Conectado. As conversas novas já começam a chegar.
        </p>
      ) : null}
    </li>
  );
}

export function WhatsAppView() {
  const [open, setOpen] = useState<string | null>(null);
  // Enquanto um QR está na tela, acompanha o estado para mostrar "conectado" assim que ler.
  const { data, error, mutate } = useWhatsApp(open ? 3000 : 0);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;

  const disconnected = data.sellers.filter(
    (row) => row.connection?.state === "desconectado" && row.connection.disconnected_at,
  );

  return (
    <>
      <PageTitle
        title="WhatsApp"
        lead="Conecte o WhatsApp de cada vendedor com um QR code, como no WhatsApp Web: as conversas chegam sozinhas ao Radar."
      />
      <Recommendation idleMinutes={data.idle_minutes} />

      {!data.enabled ? (
        <Empty title="O WhatsApp ao vivo não está ligado">
          Suba o Radar com <code className="rounded bg-linha px-1">docker compose --profile whatsapp up</code> para
          conectar números. Enquanto isso, as conversas entram pelo export, em Conversas.
        </Empty>
      ) : null}
      {data.enabled && !data.available ? (
        <p
          role="alert"
          className="mb-4 flex items-start gap-2 rounded-lg border border-atencao-forte/40 bg-atencao-marca/40 px-4 py-3 text-sm"
        >
          <TriangleAlert aria-hidden size={17} className="mt-0.5 shrink-0 text-atencao" />
          <span>
            O conector do WhatsApp (Evolution API) não respondeu. Se ele ainda não foi ligado, suba o Radar com{" "}
            <code className="rounded bg-linha px-1">docker compose --profile whatsapp up</code>. Os estados abaixo
            podem estar desatualizados.
          </span>
        </p>
      ) : null}

      {data.enabled && data.can_manage && disconnected.length > 0 ? (
        <p role="status" className="mb-4 rounded-lg border border-critico/30 bg-critico-marca/40 px-4 py-3 text-sm">
          <strong>{disconnected.map((row) => row.seller.display_name).join(", ")}</strong>{" "}
          {disconnected.length === 1 ? "está" : "estão"} com o WhatsApp desconectado: as conversas novas não estão
          chegando.
        </p>
      ) : null}

      {data.enabled ? (
        data.sellers.length === 0 ? (
          <Empty title="Nenhum vendedor para conectar">
            {data.can_manage
              ? "Cadastre os vendedores em Vendedores para conectar o WhatsApp de cada um."
              : "Seu usuário ainda não está vinculado a um vendedor. Peça para a gestão."}
          </Empty>
        ) : (
          <Panel aria-label="Números da equipe">
            <ul className="divide-y divide-linha">
              {data.sellers.map((row) => (
                <SellerCard
                  key={row.seller.id}
                  row={row}
                  canManage={data.can_manage}
                  open={open === row.seller.id}
                  onOpen={() => setOpen(row.seller.id)}
                  onClose={() => {
                    setOpen(null);
                    void mutate();
                  }}
                  onChanged={() => void mutate()}
                />
              ))}
            </ul>
          </Panel>
        )
      ) : null}
    </>
  );
}
