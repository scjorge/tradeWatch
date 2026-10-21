import { ActionIcon, AppShell, Burger, Group, Menu, NavLink, Text, Tooltip, useComputedColorScheme, useMantineColorScheme } from "@mantine/core";
import { useDisclosure, useLocalStorage } from "@mantine/hooks";
import {
  IconBell,
  IconChartCandle,
  IconFileAnalytics,
  IconLayoutDashboard,
  IconList,
  IconLogout,
  IconMoon,
  IconNotebook,
  IconPlug,
  IconSettings,
  IconShield,
  IconSun,
  IconUserCircle,
  IconWallet,
} from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { NavLink as RouterLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { ModuleInfo } from "../api/types";
import { useAuth } from "../auth/AuthContext";

const ICONS: Record<string, typeof IconList> = {
  dashboard: IconLayoutDashboard,
  chart: IconChartCandle,
  list: IconList,
  wallet: IconWallet,
  report: IconFileAnalytics,
  plug: IconPlug,
  bell: IconBell,
  notebook: IconNotebook,
  settings: IconSettings,
  shield: IconShield,
};

export function AppLayout() {
  const [opened, { toggle, close }] = useDisclosure();
  const [desktopOpened, setDesktopOpened] = useLocalStorage({ key: "sidebar-desktop-open", defaultValue: true });
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme("light");
  const modules = useQuery({ queryKey: ["modules"], queryFn: () => api<ModuleInfo[]>("/api/me/modules") });
  const nav = (modules.data ?? []).flatMap((m) => m.nav).sort((a, b) => a.order - b.order);

  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 240, breakpoint: "sm", collapsed: { mobile: !opened, desktop: !desktopOpened } }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Abrir menu" />
            <Burger
              opened={desktopOpened}
              onClick={() => setDesktopOpened((v) => !v)}
              visibleFrom="sm"
              size="sm"
              aria-label={desktopOpened ? "Recolher menu" : "Expandir menu"}
            />
            <img src="/favicon.svg" width={24} height={24} alt="" />
            <Text fw={700}>TradeWatch</Text>
            <Text size="xs" c="dimmed" visibleFrom="sm">
              v{__APP_VERSION__}
            </Text>
          </Group>
          <Group gap="xs">
            <Tooltip label={scheme === "dark" ? "Tema claro" : "Tema escuro"}>
              <ActionIcon variant="subtle" onClick={() => setColorScheme(scheme === "dark" ? "light" : "dark")} aria-label="Alternar tema">
                {scheme === "dark" ? <IconSun size={18} /> : <IconMoon size={18} />}
              </ActionIcon>
            </Tooltip>
            <Menu position="bottom-end">
              <Menu.Target>
                <ActionIcon variant="subtle" aria-label="Conta">
                  <IconUserCircle size={20} />
                </ActionIcon>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{user?.email}</Menu.Label>
                <Menu.Item leftSection={<IconSettings size={14} />} onClick={() => navigate("/settings")}>
                  Configurações
                </Menu.Item>
                <Menu.Item color="red" leftSection={<IconLogout size={14} />} onClick={() => void logout()}>
                  Sair
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs">
        {nav.map((item) => {
          const Icon = ICONS[item.icon] ?? IconList;
          const active = item.path === "/" ? location.pathname === "/" : location.pathname.startsWith(item.path);
          return (
            <NavLink
              key={item.path}
              component={RouterLink}
              to={item.path}
              label={item.label}
              leftSection={<Icon size={18} stroke={1.6} />}
              active={active}
              onClick={close}
              style={{ borderRadius: 6 }}
            />
          );
        })}
      </AppShell.Navbar>
      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
