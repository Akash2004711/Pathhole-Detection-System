// Authentication helpers built on the Firebase client SDK.
// On register, the Auth account is created in the browser, then the users/{uid}
// Firestore profile is created through the BACKEND (/api/auth/register-profile)
// using the Admin SDK. This avoids any dependency on client Firestore rules and
// lets a new account optionally choose the government-authority role by
// supplying the shared AUTHORITY_SIGNUP_CODE.

async function registerUser(email, password, displayName, role = "user", code = null) {
    const auth = PDS.auth();
    if (!auth) throw new Error("Firebase is not configured. Set the Firebase web config in backend/.env.");
    let cred;
    try {
        cred = await auth.createUserWithEmailAndPassword(email, password);
    } catch (err) {
        throw new Error(err && err.message ? err.message : "Could not create the account.");
    }
    if (displayName) { try { await cred.user.updateProfile({ displayName }); } catch (_) { /* non-fatal */ } }

    // Create the profile (and set the chosen role) via the backend Admin SDK.
    const token = await cred.user.getIdToken();
    let res, data = {};
    try {
        res = await fetch(PDS.apiBase + "/api/auth/register-profile", {
            method: "POST",
            headers: { "Content-Type": "application/json", "Authorization": "Bearer " + token },
            body: JSON.stringify({ role, display_name: displayName || "", code }),
        });
        data = await res.json().catch(() => ({}));
    } catch (e) {
        throw new Error("Could not reach the backend to finish registration.");
    }
    if (!res.ok) {
        // Roll back the half-created Auth account so the user can retry.
        try { await cred.user.delete(); } catch (_) { /* ignore */ }
        throw new Error(data.detail || "Registration failed.");
    }
    // Refresh the ID token so the new role claim is available immediately.
    try { await cred.user.getIdToken(true); } catch (_) { /* ignore */ }
    return cred.user;
}

async function loginUser(email, password) {
    const auth = PDS.auth();
    if (!auth) throw new Error("Firebase is not configured. Set the Firebase web config in backend/.env.");
    const cred = await auth.signInWithEmailAndPassword(email, password);
    return cred.user;
}

async function logoutUser() {
    const auth = PDS.auth();
    if (auth) await auth.signOut();
    window.location.href = "index.html";
}

// Resolve the signed-in user's role from Firestore (source of truth).
async function getUserRole(uid) {
    const db = firebase.firestore();
    const snap = await db.collection("users").doc(uid).get();
    if (!snap.exists) return "user";
    return (snap.data() || {}).role || "user";
}

// Guard a dashboard page: require a signed-in user with an allowed role.
async function requireAuth(allowedRoles) {
    await PDS.loadConfig();
    const auth = PDS.auth();
    if (!auth) {
        alert("Authentication is unavailable: Firebase is not configured. " +
            "Fill in the Firebase web config in backend/.env and restart the backend.");
        return null;
    }
    const user = await new Promise(resolve => {
        const unsub = auth.onAuthStateChanged(u => { unsub(); resolve(u); });
    });
    if (!user) {
        window.location.href = "index.html";
        return null;
    }
    const role = await getUserRole(user.uid);
    if (allowedRoles && !allowedRoles.includes(role)) {
        window.location.href = role === "government_authority" ? "authority.html" : "user.html";
        return null;
    }
    return { user, role };
}
