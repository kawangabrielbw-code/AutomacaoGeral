let csrf = "";
const message = document.getElementById("login-message");
fetch("/api/session", {signal:AbortSignal.timeout ? AbortSignal.timeout(15000) : undefined})
  .then(async response => {
    const data=await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(data.detail || `Erro HTTP ${response.status}`);
    if(typeof data.csrf_token!=="string"||!data.csrf_token) throw new Error("Sessão inválida; recarregue a página.");
    return data;
  })
  .then(s => { csrf = s.csrf_token; if (s.authenticated) location.href = "/dashboard"; })
  .catch(error => { message.textContent = error.name==="TimeoutError" ? "O servidor demorou demais para responder." : error.message; message.className="message error"; });
document.getElementById("login-form").addEventListener("submit", async event => {
  event.preventDefault(); message.textContent = "Verificando acesso…";
  try {
    const response = await fetch("/api/login", {method:"POST", headers:{"Content-Type":"application/json","X-CSRF-Token":csrf}, body:JSON.stringify({password:document.getElementById("password").value}), signal:AbortSignal.timeout ? AbortSignal.timeout(15000) : undefined});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Não foi possível entrar.");
    location.href = "/dashboard";
  } catch (error) { message.textContent = error.message; message.className = "message error"; }
});
