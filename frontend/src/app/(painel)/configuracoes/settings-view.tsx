"use client";

import { useState } from "react";
import useSWR from "swr";

import { Button, ErrorNote, Loading, PageTitle, SelectField } from "@/components/ui";
import { api, type Schemas, unwrap } from "@/lib/api/client";
import { can, useMe, usePlaybooks, useUsers } from "@/lib/api/hooks";
import { formatDateTime, roleLabel } from "@/lib/format";

type Settings = Schemas["TenantSettings"];
type Role = Schemas["Role"];

const INPUT = "w-28 rounded-md border border-linha-forte bg-folha px-2 py-1.5 text-tinta numeros";
const ROLES: Role[] = ["admin", "gestor", "auditor", "vendedor"];

function NumberField({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium">{label}</span>
      <input
        type="number"
        min={0}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className={INPUT}
      />
      <span className="text-xs text-grafite">{hint}</span>
    </label>
  );
}

type Notice = { kind: "ok" | "erro"; text: string };

export function SettingsView() {
  const tenant = useSWR("tenant", () => unwrap(api.GET("/api/v1/tenant")), { revalidateOnFocus: false });
  const [notice, setNotice] = useState<Notice | null>(null);
  if (tenant.error) return <ErrorNote error={tenant.error} />;
  if (!tenant.data) return <Loading />;
  // A chave recria o formulário com os valores salvos depois de cada gravação.
  return (
    <SettingsForm
      key={JSON.stringify(tenant.data)}
      tenant={tenant.data}
      notice={notice}
      onNotice={setNotice}
      onSaved={() => void tenant.mutate()}
    />
  );
}

function SettingsForm({
  tenant,
  notice,
  onNotice,
  onSaved,
}: {
  tenant: Schemas["TenantOut"];
  notice: Notice | null;
  onNotice: (notice: Notice | null) => void;
  onSaved: () => void;
}) {
  const { data: me } = useMe();
  const retention = useSWR(can(me, "privacidade") ? "retention" : null, () =>
    unwrap(api.GET("/api/v1/privacy/retention")),
  );
  const playbooks = usePlaybooks();
  const users = useUsers(can(me, "gerir"));
  const [name, setName] = useState(tenant.name);
  const [playbook, setPlaybook] = useState(tenant.default_playbook);
  const [settings, setSettings] = useState<Settings>(tenant.settings);
  const [pending, setPending] = useState(false);
  const message = notice;
  const setMessage = onNotice;
  const editable = can(me, "configurar");

  function update<K extends keyof Settings>(key: K, value: Settings[K]) {
    setSettings((current) => ({ ...current, [key]: value }));
  }

  async function save() {
    setPending(true);
    setMessage(null);
    try {
      await unwrap(
        api.PATCH("/api/v1/tenant", { body: { name, default_playbook: playbook, settings } }),
      );
      await retention.mutate();
      setMessage({ kind: "ok", text: "Configurações salvas." });
      onSaved();
    } catch (exc) {
      setMessage({ kind: "erro", text: exc instanceof Error ? exc.message : "Não foi possível salvar." });
    } finally {
      setPending(false);
    }
  }

  async function runRetention() {
    const ok = window.confirm(
      "Aplicar a retenção agora? O texto original e os áudios além do prazo serão apagados, sem volta.",
    );
    if (!ok) return;
    setPending(true);
    try {
      const report = await unwrap(api.POST("/api/v1/privacy/retention/run"));
      await retention.mutate();
      setMessage({
        kind: "ok",
        text: `Retenção aplicada: ${report.raw_messages_purged} mensagem(ns), ${report.media_files_deleted} áudio(s) e ${report.conversations_deleted} conversa(s).`,
      });
    } catch (exc) {
      setMessage({ kind: "erro", text: exc instanceof Error ? exc.message : "A retenção falhou." });
    } finally {
      setPending(false);
    }
  }

  const reveal = new Set(settings.reveal_roles ?? []);
  return (
    <>
      <PageTitle title="Configurações" />
      <fieldset disabled={!editable || pending} className="space-y-10">
        <section aria-labelledby="empresa" className="space-y-4">
          <h2 id="empresa" className="text-lg font-bold">
            Empresa e análise
          </h2>
          <div className="flex flex-wrap gap-6">
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Nome da empresa</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="w-72 rounded-md border border-linha-forte bg-folha px-2 py-1.5"
              />
            </label>
            <SelectField label="Playbook padrão" value={playbook} onChange={(e) => setPlaybook(e.target.value)}>
              {playbooks.data?.map((p) => (
                <option key={p.slug} value={p.slug}>
                  {p.name}
                </option>
              ))}
            </SelectField>
            <SelectField
              label="Uso de LLM"
              value={settings.llm_mode ?? "herdar"}
              onChange={(e) => update("llm_mode", e.target.value as Settings["llm_mode"])}
            >
              <option value="herdar">Como a instalação definir</option>
              <option value="cloud">Nuvem gratuita (texto mascarado)</option>
              <option value="local">Só local (Ollama, nada sai da máquina)</option>
              <option value="off">Sem LLM (só regras e métricas)</option>
            </SelectField>
          </div>
          <div className="flex flex-wrap gap-6">
            <NumberField
              label="Meta de resposta (min)"
              hint="Minutos úteis para responder o cliente."
              value={settings.response_sla_minutes ?? 15}
              onChange={(v) => update("response_sla_minutes", v)}
            />
            <NumberField
              label="Follow-up (horas)"
              hint="Silêncio do cliente que pede retomada."
              value={settings.follow_up_hours ?? 48}
              onChange={(v) => update("follow_up_hours", v)}
            />
          </div>
        </section>

        <section aria-labelledby="privacidade" className="space-y-4">
          <h2 id="privacidade" className="text-lg font-bold">
            Privacidade e retenção
          </h2>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={settings.mask_person_names ?? true}
              onChange={(event) => update("mask_person_names", event.target.checked)}
            />
            Mascarar nomes de pessoas (CPF, telefone e outros dados são sempre mascarados)
          </label>
          <fieldset className="text-sm">
            <legend className="font-medium">Quem pode ver o texto original e ouvir os áudios</legend>
            <div className="mt-1 flex flex-wrap gap-4">
              {ROLES.filter((role) => role !== "vendedor").map((role) => (
                <label key={role} className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={reveal.has(role)}
                    onChange={(event) => {
                      const next = new Set(reveal);
                      if (event.target.checked) next.add(role);
                      else next.delete(role);
                      update("reveal_roles", [...next]);
                    }}
                  />
                  {roleLabel(role)}
                </label>
              ))}
            </div>
            <p className="mt-1 text-xs text-grafite">Cada acesso ao original fica na trilha de auditoria.</p>
          </fieldset>
          <div className="flex flex-wrap gap-6">
            <NumberField
              label="Texto original (dias)"
              hint="Depois disso só o mascarado fica. 0 = nunca apagar."
              value={settings.retention_raw_days ?? 90}
              onChange={(v) => update("retention_raw_days", v)}
            />
            <NumberField
              label="Áudios (dias)"
              hint="A transcrição segue a regra do texto."
              value={settings.retention_media_days ?? 30}
              onChange={(v) => update("retention_media_days", v)}
            />
            <NumberField
              label="Conversa inteira (dias)"
              hint="Sem mensagens novas no período. 0 = nunca."
              value={settings.retention_conversation_days ?? 0}
              onChange={(v) => update("retention_conversation_days", v)}
            />
          </div>
          {retention.data ? (
            <div className="rounded-lg border border-linha bg-folha p-3 text-sm">
              <p>
                Se a retenção rodasse agora, apagaria o original de{" "}
                <strong className="numeros">{retention.data.pending.raw_messages_purged}</strong> mensagem(ns),{" "}
                <strong className="numeros">{retention.data.pending.media_files_deleted}</strong> áudio(s) e{" "}
                <strong className="numeros">{retention.data.pending.conversations_deleted}</strong> conversa(s). O
                agendador aplica a cada 6 horas.
              </p>
              <Button variant="danger" className="mt-2" onClick={runRetention}>
                Aplicar retenção agora
              </Button>
            </div>
          ) : null}
        </section>

        {editable ? (
          <div className="flex items-center gap-3">
            <Button variant="primary" onClick={save}>
              Salvar configurações
            </Button>
          </div>
        ) : (
          <p className="text-sm text-grafite">Só a administração pode mudar as configurações.</p>
        )}
      </fieldset>
      {message ? (
        <p role={message.kind === "erro" ? "alert" : "status"} className={`mt-3 text-sm ${message.kind === "erro" ? "text-critico" : "text-ok"}`}>
          {message.text}
        </p>
      ) : null}

      {users.data ? (
        <section aria-labelledby="equipe" className="mt-12">
          <h2 id="equipe" className="mb-3 text-lg font-bold">
            Pessoas com acesso
          </h2>
          <table className="w-full text-left text-sm">
            <thead className="border-b border-linha-forte text-grafite">
              <tr>
                <th className="py-2 font-medium">Nome</th>
                <th className="py-2 font-medium">E-mail</th>
                <th className="py-2 font-medium">Papel</th>
                <th className="py-2 font-medium">Último acesso</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-linha">
              {users.data.items.map((user) => (
                <tr key={user.id} className={user.is_active ? "" : "text-grafite"}>
                  <td className="py-2">{user.name}</td>
                  <td className="py-2">{user.email}</td>
                  <td className="py-2">{roleLabel(user.role)}</td>
                  <td className="py-2 text-grafite">
                    {user.last_login_at ? formatDateTime(user.last_login_at) : "nunca entrou"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </>
  );
}
