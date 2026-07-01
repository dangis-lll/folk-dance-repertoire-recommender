document.addEventListener("submit", (event) => {
  const form = event.target.closest("form[data-confirm]");
  if (!form) {
    return;
  }

  const message = form.dataset.confirm;
  if (message && !window.confirm(message)) {
    event.preventDefault();
  }
});

const normalizeWorkSearchText = (value) => (value || "").toLowerCase().replace(/\s+/g, "");

document.querySelectorAll("[data-work-select-filter]").forEach((input) => {
  const field = input.closest(".work-select-field") || input.parentElement;
  const select = field ? field.querySelector('select[name="work_id"]') : null;
  const count = field ? field.querySelector("[data-work-select-count]") : null;
  if (!select) {
    return;
  }

  const options = Array.from(select.options).map((option, index) => ({
    option,
    index,
    text: normalizeWorkSearchText(option.textContent),
    isEmpty: !option.value,
  }));

  const update = () => {
    const term = normalizeWorkSearchText(input.value);
    let visible = 0;
    options.forEach(({ option, text, isEmpty }) => {
      const matched = isEmpty || !term || text.includes(term);
      option.hidden = !matched;
      option.disabled = !matched;
      if (matched && !isEmpty) {
        visible += 1;
      }
    });

    const selected = select.selectedOptions[0];
    if (selected && selected.disabled) {
      select.value = "";
    }
    if (count) {
      count.textContent = term ? `匹配 ${visible} 个剧目` : `共 ${options.filter((item) => !item.isEmpty).length} 个剧目`;
    }
  };

  input.addEventListener("input", update);
  update();
});

document.querySelectorAll("[data-recommend-form]").forEach((form) => {
  const textarea = form.querySelector("[data-recommend-textarea]");
  const count = form.querySelector("[data-recommend-count]");
  const submit = form.querySelector(".recommend-submit");

  const updateCount = () => {
    if (!textarea || !count) {
      return;
    }
    const length = textarea.value.trim().length;
    count.textContent = length
      ? `已输入 ${length} 字。条件越具体，推荐越稳定。`
      : "可以直接输入剧目名，也可以描述完整选剧需求。";
  };

  if (textarea) {
    textarea.addEventListener("input", updateCount);
    updateCount();
  }

  form.addEventListener("submit", () => {
    if (!submit) {
      return;
    }
    submit.classList.add("is-loading");
    submit.textContent = "正在分析...";
  });
});
