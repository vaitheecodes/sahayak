import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { metaApi } from '../../api/tickets';
import type { Meta, TicketStatus } from '../../api/types';
import { useApi } from '../../auth/SessionProvider';

// Display config from /api/meta: the admin's status labels and the
// categories (they are data on the server, not a fixed list).
//
// The server's default labels are staff words ("In Progress", "Pending
// Customer"). Customers see the app's own words instead (status.* in the
// locale: Open / In progress / Pending / Resolved / Closed, translatable);
// a label the admin has renamed in Settings still wins.
const SERVER_DEFAULT_LABELS: Record<TicketStatus, string> = {
  open: 'Open',
  in_progress: 'In Progress',
  pending_customer: 'Pending Customer',
  resolved: 'Resolved',
  closed: 'Closed',
};

type MetaValue = {
  categories: string[];
  /** False until /api/meta has answered once. */
  loaded: boolean;
  failed: boolean;
  statusLabel: (status: string) => string;
  categoryLabel: (name: string | null | undefined) => string;
  reload: () => Promise<void>;
};

const MetaContext = createContext<MetaValue | null>(null);

/** A category without a label reads as a phrase, as on the web. */
export function categoryPhrase(name: string): string {
  return name.replace(/_/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

export function MetaProvider({ children }: { children: ReactNode }) {
  const api = useApi();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [failed, setFailed] = useState(false);
  const { t } = useTranslation();

  const reload = useCallback(async () => {
    try {
      setMeta(await metaApi.get(api));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [api]);

  useEffect(() => {
    // The request is async: state is only set after it answers.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    reload();
  }, [reload]);

  const value = useMemo<MetaValue>(() => {
    const renamed: Partial<Record<TicketStatus, string>> = meta?.status_labels ?? {};
    const categoryLabels = meta?.category_labels ?? {};
    return {
      categories: meta?.categories ?? [],
      loaded: meta !== null,
      failed,
      statusLabel: (s) => {
        const admin = renamed[s as TicketStatus];
        if (admin && admin !== SERVER_DEFAULT_LABELS[s as TicketStatus]) return admin;
        return t(`status.${s}`, { defaultValue: s });
      },
      categoryLabel: (c) => (c ? categoryLabels[c] ?? categoryPhrase(c) : '—'),
      reload,
    };
  }, [meta, failed, reload, t]);

  return <MetaContext.Provider value={value}>{children}</MetaContext.Provider>;
}

export function useMeta(): MetaValue {
  const value = useContext(MetaContext);
  if (!value) throw new Error('useMeta must be used inside MetaProvider');
  return value;
}
