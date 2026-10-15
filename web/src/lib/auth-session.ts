"use client";

import { login } from "@/lib/api";
import { HttpError } from "@/lib/request";
import { clearStoredAuthSession, getStoredAuthSession, setStoredAuthSession, type StoredAuthSession } from "@/store/auth";

// 同一次页面加载内只向服务端校验一次密钥，客户端切换页面时直接复用结果。
let validatedKey = "";
let pendingValidation: Promise<StoredAuthSession | null> | null = null;

function isAuthRejected(error: unknown) {
  const status = error instanceof HttpError ? error.status : undefined;
  return status === 401 || status === 403;
}

async function validateAuthSession(storedSession: StoredAuthSession): Promise<StoredAuthSession | null> {
  try {
    const data = await login(storedSession.key);
    const nextSession: StoredAuthSession = {
      key: storedSession.key,
      role: data.role,
      subjectId: data.subject_id,
      name: data.name,
    };
    await setStoredAuthSession(nextSession);
    validatedKey = nextSession.key;
    return nextSession;
  } catch (error) {
    // 只有服务端明确拒绝密钥时才退出登录；超时、网关错误等临时故障保留本地会话。
    if (isAuthRejected(error)) {
      await clearStoredAuthSession();
      return null;
    }
    return storedSession;
  }
}

export async function getValidatedAuthSession(): Promise<StoredAuthSession | null> {
  const storedSession = await getStoredAuthSession();
  if (!storedSession) {
    validatedKey = "";
    return null;
  }
  if (validatedKey === storedSession.key) {
    return storedSession;
  }

  if (!pendingValidation) {
    pendingValidation = validateAuthSession(storedSession).finally(() => {
      pendingValidation = null;
    });
  }
  return pendingValidation;
}
