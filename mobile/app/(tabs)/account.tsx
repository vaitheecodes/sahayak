import { router } from 'expo-router';
import { AccountScreen } from '../../src/features/account/AccountScreen';

export default function AccountTab() {
  return <AccountScreen onChangePassword={() => router.push('/password')} />;
}
