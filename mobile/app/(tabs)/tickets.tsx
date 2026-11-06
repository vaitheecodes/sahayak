import { useTranslation } from 'react-i18next';
import { Inbox } from 'lucide-react-native';
import { useTheme } from '../../src/theme/ThemeProvider';
import { EmptyState } from '../../src/ui/EmptyState';
import { Screen } from '../../src/ui/Screen';

// Stage 2 replaces this with the ticket list.
export default function TicketsTab() {
  const { t } = useTranslation();
  const { colors } = useTheme();
  return (
    <Screen scroll={false} edges={[]}>
      <EmptyState
        icon={<Inbox size={32} color={colors.mutedFg} />}
        title={t('placeholder.ticketsTitle')}
        body={t('placeholder.ticketsBody')}
      />
    </Screen>
  );
}
