import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "../auth/AuthContext";
import { LoginPage } from "../pages/auth/AuthPages";

function renderLogin() {
  return render(
    <MantineProvider>
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <AuthProvider>
            <LoginPage />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe("LoginPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("mostra erro do servidor e oferece reenvio quando o e-mail não foi confirmado", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      if (String(url).includes("/api/me")) return new Response(JSON.stringify({ error: { code: "unauthorized", message: "x" } }), { status: 401 });
      return new Response(JSON.stringify({ error: { code: "email_not_verified", message: "Confirme seu e-mail antes de entrar." } }), { status: 403 });
    });
    renderLogin();
    fireEvent.change(await screen.findByLabelText(/E-mail/), { target: { value: "ana@example.com" } });
    fireEvent.change(screen.getByLabelText(/Senha/), { target: { value: "Senha-Forte-123" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));
    await waitFor(() => expect(screen.getByText(/Confirme seu e-mail/)).toBeInTheDocument());
    expect(screen.getByText(/Reenviar e-mail/)).toBeInTheDocument();
    const loginCall = fetchMock.mock.calls.find(([u]) => String(u) === "/api/auth/login");
    expect(loginCall?.[1]?.method).toBe("POST");
    expect(JSON.parse(String(loginCall?.[1]?.body))).toEqual({ email: "ana@example.com", password: "Senha-Forte-123" });
  });
});
