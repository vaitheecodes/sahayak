import type { ReactElement, ReactNode } from 'react';
import { Text } from 'react-native';
import { screen, waitFor } from '@testing-library/react-native';
import type { TicketDetail, TicketSummary } from '../src/api/types';
import { useSession } from '../src/auth/SessionProvider';
import { MetaProvider } from '../src/features/meta/MetaProvider';
import { fakeFetch, type FakeReply, type FakeRequest } from './fakeFetch';
import { renderWithSession, storeToken } from './render';

type Handler = FakeReply | ((req: FakeRequest) => FakeReply | Promise<FakeReply>);

export const META = {
  status_labels: { open: 'Open', in_progress: 'In Progress', pending_customer: 'Waiting on you', resolved: 'Resolved', closed: 'Closed' },
  categories: ['BILLING', 'LOGIN_ACCESS'],
  category_labels: { BILLING: 'Billing & payments' },
  product: { name: 'the product', support_team_name: 'Support' },
  kb_entries: 0,
};

const ME = { user_id: 'C1', role: 'customer', name: 'Asha Rao', email: 'asha@example.com', must_change_password: false };

// Screens only mount once signed in, as in the app's route guards.
function SignedIn({ children }: { children: ReactNode }) {
  const { status } = useSession();
  return status === 'signedIn' ? <MetaProvider>{children}</MetaProvider> : <Text>gate:{status}</Text>;
}

export async function renderSignedIn(ui: ReactElement, routes: Record<string, Handler>) {
  await storeToken('tok');
  const fake = fakeFetch({ 'GET /api/auth/me': { body: ME }, 'GET /api/meta': { body: META }, ...routes });
  const result = await renderWithSession(<SignedIn>{ui}</SignedIn>, fake.impl);
  await waitFor(() => expect(screen.queryByText(/^gate:/)).not.toBeOnTheScreen());
  return { ...result, ...fake };
}

export function summary(overrides: Partial<TicketSummary> = {}): TicketSummary {
  return {
    ticket_id: 'TCK-00000001',
    ticket_type: 'ticket',
    subject: 'Payslip not loading',
    status: 'open',
    priority: 'medium',
    category: 'BILLING',
    created_at: '2026-11-06T09:00:00+00:00',
    last_updated: '2026-11-06T09:00:00+00:00',
    unread: false,
    escalated: false,
    ...overrides,
  };
}

export function detail(overrides: Partial<TicketDetail> = {}, ticket: Partial<TicketDetail['ticket']> = {}): TicketDetail {
  return {
    incident_notice: null,
    chat: null,
    ticket: {
      ticket_id: 'TCK-00000001',
      ticket_type: 'ticket',
      subject: 'Payslip not loading',
      status: 'pending_customer',
      route: 'clarify',
      priority: 'high',
      category: 'BILLING',
      created_at: '2026-11-06T09:00:00+00:00',
      ...ticket,
    },
    messages: [
      {
        message_id: 'M1',
        sender: 'customer',
        sender_name: 'Asha Rao',
        sender_role: 'Customer',
        to: 'Support',
        subject: null,
        incident_update: false,
        message: 'My payslip page is blank.',
        created_at: '2026-11-06T09:00:00+00:00',
        attachments: [],
      },
      {
        message_id: 'M2',
        sender: 'ai',
        sender_name: 'Support Bot',
        sender_role: 'AI Assistant',
        to: 'Asha Rao',
        subject: null,
        incident_update: false,
        message: 'Hi Asha,\n\nWhich browser are you using?\n\n- Chrome\n- Safari',
        created_at: '2026-11-06T09:00:05+00:00',
        attachments: [],
      },
    ],
    ...overrides,
  };
}
