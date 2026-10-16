import { Alert, Anchor, Button, Center, Paper, PasswordInput, Stack, Text, TextInput, Title } from "@mantine/core";
import { IconCheck } from "@tabler/icons-react";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";

function Frame({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <Center mih="100vh" p="md">
      <Paper withBorder radius="md" p="xl" w="100%" maw={420}>
        <Stack gap={4} mb="lg">
          <img src="/favicon.svg" width={36} height={36} alt="" />
          <Title order={3}>{title}</Title>
          {subtitle && (
            <Text size="sm" c="dimmed">
              {subtitle}
            </Text>
          )}
        </Stack>
        {children}
      </Paper>
    </Center>
  );
}

function useHashToken(): string {
  const { hash } = useLocation();
  return new URLSearchParams(hash.replace(/^#/, "")).get("t") ?? "";
}

const PASSWORD_HINT = "Mínimo de 10 caracteres, com três tipos entre minúsculas, maiúsculas, números e símbolos.";

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [resent, setResent] = useState(false);

  if (user) return <Navigate to={(location.state as { from?: string })?.from ?? "/"} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate((location.state as { from?: string })?.from ?? "/", { replace: true });
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Frame title="Entrar no TradeWatch" subtitle="Acompanhamento de operações em modo somente leitura.">
      <form onSubmit={submit}>
        <Stack>
          {error && (
            <Alert color="red">
              {error.message}
              {error.code === "email_not_verified" && !resent && (
                <Anchor
                  component="button"
                  type="button"
                  size="sm"
                  display="block"
                  mt={4}
                  onClick={async () => {
                    await api("/api/auth/resend-verification", { body: { email } });
                    setResent(true);
                  }}
                >
                  Reenviar e-mail de confirmação
                </Anchor>
              )}
              {resent && <Text size="sm">E-mail reenviado.</Text>}
            </Alert>
          )}
          <TextInput label="E-mail" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.currentTarget.value)} />
          <PasswordInput label="Senha" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.currentTarget.value)} />
          <Button type="submit" loading={busy}>
            Entrar
          </Button>
          <Text size="sm" ta="center">
            <Anchor component={Link} to="/forgot-password">
              Esqueci minha senha
            </Anchor>{" "}
            ·{" "}
            <Anchor component={Link} to="/register">
              Criar conta
            </Anchor>
          </Text>
        </Stack>
      </form>
    </Frame>
  );
}

export function RegisterPage() {
  const [form, setForm] = useState({ display_name: "", email: "", password: "", confirm: "" });
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (form.password !== form.confirm) return setError("As senhas não coincidem.");
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ message: string }>("/api/auth/register", { body: { email: form.email, password: form.password, display_name: form.display_name } });
      setDone(r.message);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (done)
    return (
      <Frame title="Verifique seu e-mail">
        <Alert color="teal" icon={<IconCheck />}>
          {done}
        </Alert>
        <Anchor component={Link} to="/login" size="sm" mt="md" display="block">
          Voltar para o login
        </Anchor>
      </Frame>
    );

  return (
    <Frame title="Criar conta">
      <form onSubmit={submit}>
        <Stack>
          {error && <Alert color="red">{error}</Alert>}
          <TextInput label="Nome" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.currentTarget.value })} />
          <TextInput label="E-mail" type="email" required autoComplete="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.currentTarget.value })} />
          <PasswordInput label="Senha" description={PASSWORD_HINT} required autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.currentTarget.value })} />
          <PasswordInput label="Confirme a senha" required autoComplete="new-password" value={form.confirm} onChange={(e) => setForm({ ...form, confirm: e.currentTarget.value })} />
          <Button type="submit" loading={busy}>
            Criar conta
          </Button>
          <Anchor component={Link} to="/login" size="sm" ta="center">
            Já tenho conta
          </Anchor>
        </Stack>
      </form>
    </Frame>
  );
}

export function VerifyEmailPage() {
  const token = useHashToken();
  const [state, setState] = useState<{ ok: boolean; msg: string } | null>(null);
  const ran = useRef(false);
  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    if (!token) return setState({ ok: false, msg: "Link inválido." });
    api<{ message: string }>("/api/auth/verify-email", { body: { token } })
      .then((r) => setState({ ok: true, msg: r.message }))
      .catch((e: Error) => setState({ ok: false, msg: e.message }));
    // remove o token da barra de endereço
    window.history.replaceState(null, "", window.location.pathname);
  }, [token]);
  return (
    <Frame title="Confirmação de e-mail">
      {state ? <Alert color={state.ok ? "teal" : "red"}>{state.msg}</Alert> : <Text>Confirmando…</Text>}
      <Anchor component={Link} to="/login" size="sm" mt="md" display="block">
        Ir para o login
      </Anchor>
    </Frame>
  );
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Frame title="Recuperar senha" subtitle="Enviaremos um link de redefinição válido por 30 minutos.">
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            const r = await api<{ message: string }>("/api/auth/forgot-password", { body: { email } });
            setMsg(r.message);
          } catch (err) {
            setMsg((err as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Stack>
          {msg && <Alert color="blue">{msg}</Alert>}
          <TextInput label="E-mail" type="email" required value={email} onChange={(e) => setEmail(e.currentTarget.value)} />
          <Button type="submit" loading={busy}>
            Enviar link
          </Button>
          <Anchor component={Link} to="/login" size="sm" ta="center">
            Voltar
          </Anchor>
        </Stack>
      </form>
    </Frame>
  );
}

export function ResetPasswordPage() {
  const token = useHashToken();
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [state, setState] = useState<{ ok: boolean; msg: string } | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Frame title="Definir nova senha">
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (pw !== confirm) return setState({ ok: false, msg: "As senhas não coincidem." });
          setBusy(true);
          try {
            const r = await api<{ message: string }>("/api/auth/reset-password", { body: { token, new_password: pw } });
            setState({ ok: true, msg: r.message });
            window.history.replaceState(null, "", window.location.pathname);
          } catch (err) {
            setState({ ok: false, msg: (err as Error).message });
          } finally {
            setBusy(false);
          }
        }}
      >
        <Stack>
          {state && <Alert color={state.ok ? "teal" : "red"}>{state.msg}</Alert>}
          {!state?.ok && (
            <>
              <PasswordInput label="Nova senha" description={PASSWORD_HINT} required value={pw} onChange={(e) => setPw(e.currentTarget.value)} autoComplete="new-password" />
              <PasswordInput label="Confirme" required value={confirm} onChange={(e) => setConfirm(e.currentTarget.value)} autoComplete="new-password" />
              <Button type="submit" loading={busy} disabled={!token}>
                Redefinir
              </Button>
            </>
          )}
          <Anchor component={Link} to="/login" size="sm" ta="center">
            Ir para o login
          </Anchor>
        </Stack>
      </form>
    </Frame>
  );
}
