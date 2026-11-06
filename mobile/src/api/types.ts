// Response shapes from backend/main.py and docs/API.md (customer side).

export type Role = 'customer' | 'technician' | 'manager' | 'admin';

export type LoginResponse = {
  user_id: string;
  role: Role;
  name: string;
  must_change_password: boolean;
  token: string;
};

export type Me = {
  user_id: string;
  role: Role;
  name: string;
  email: string;
  must_change_password: boolean;
};
