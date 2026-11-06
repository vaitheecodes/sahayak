import { router } from 'expo-router';
import { TicketListScreen } from '../../src/features/tickets/TicketListScreen';

export default function TicketsTab() {
  return (
    <TicketListScreen
      onOpen={(id) => router.push({ pathname: '/tickets/[id]', params: { id } })}
      onNew={() => router.push('/tickets/new')}
    />
  );
}
