import { ChangePasswordScreen } from '../src/features/auth/ChangePasswordScreen';

// Forced first-sign-in change; the root layout's guard moves on to the
// tabs once must_change_password is cleared.
export default function ForcedChangePassword() {
  return <ChangePasswordScreen mode="forced" />;
}
