import { Alert } from 'react-native';
import { router } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ChangePasswordScreen } from '../src/features/auth/ChangePasswordScreen';

export default function ChangePassword() {
  const { t } = useTranslation();
  return (
    <ChangePasswordScreen
      mode="voluntary"
      onDone={() => {
        Alert.alert(t('password.saved'));
        router.back();
      }}
    />
  );
}
