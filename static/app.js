(() => {
  const timer = document.getElementById("t");
  if (!timer) return;

  let remaining = Number(timer.dataset.s || 0);
  const paymentForm = timer.parentElement.querySelector(
    'form[method="post"]'
  );

  function updateTimer() {
    const minutes = Math.floor(remaining / 60);
    const seconds = remaining % 60;

    timer.textContent =
      String(minutes).padStart(2, "0") + ":" +
      String(seconds).padStart(2, "0");

    if (remaining <= 0) {
      timer.textContent = "00:00 — EXPIRED";
      if (paymentForm) paymentForm.hidden = true;
      return;
    }

    remaining--;
    setTimeout(updateTimer, 1000);
  }

  updateTimer();
})();