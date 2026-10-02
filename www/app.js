fetch("/dados.json")
  .then((r) => r.json())
  .then((d) => {
    document.getElementById("info").textContent = d.mensagem;
  });
