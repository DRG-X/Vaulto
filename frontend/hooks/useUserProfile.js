import { useState, useCallback } from "react";
import { useAuth } from "../contexts/AuthContext";
import { getUserProfile, createUserProfile, checkUserStatus } from "../lib/api";

export function useUserProfile() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  /** Lightweight check — returns { exists: boolean } */
  const checkStatus = useCallback(async () => {
    if (!isLoaded || !isSignedIn) return null;
    const token = await getToken();
    return checkUserStatus(token);
  }, [getToken, isLoaded, isSignedIn]);

  const fetchProfile = useCallback(async () => {
    if (!isLoaded || !isSignedIn) return null;
    
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const data = await getUserProfile(token);
      setProfile(data);
      return data;
    } catch (err) {
      setError(err);
      throw err;
    } finally {
      setLoading(false);
    }
  }, [getToken, isLoaded, isSignedIn]);

  const createProfile = useCallback(async (profileData) => {
    if (!isLoaded || !isSignedIn) return null;
    
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const data = await createUserProfile(token, profileData);
      setProfile(data);
      return data;
    } catch (err) {
      setError(err);
      throw err;
    } finally {
      setLoading(false);
    }
  }, [getToken, isLoaded, isSignedIn]);

  return {
    profile,
    loading,
    error,
    checkStatus,
    fetchProfile,
    createProfile,
  };
}

