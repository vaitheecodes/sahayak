import { router } from 'expo-router';
import { NewTicketScreen } from '../../src/features/tickets/NewTicketScreen';

export default function NewTicketRoute() {
  return (
    <NewTicketScreen
      // Swap the form for the new ticket's thread, where the AI's first
      // reply (or the hand-off note) already is.
      onCreated={(created) => router.replace({ pathname: '/tickets/[id]', params: { id: created.ticket_id } })}
    />
  );
}
