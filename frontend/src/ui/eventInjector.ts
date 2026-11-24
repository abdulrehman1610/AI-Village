import { fetchWorld, injectEvent } from "../net/apiClient";

export interface EventInjectorOptions {
  formEl: HTMLFormElement | null;
  locationSelectEl: HTMLSelectElement | null;
  textInputEl: HTMLInputElement | null;
  submitBtnEl: HTMLButtonElement | null;
  feedbackEl: HTMLElement | null;
  onFocusChange?: (focused: boolean) => void;
}

function isFormControlFocused(formEl: HTMLFormElement): boolean {
  const active = document.activeElement;
  if (!(active instanceof Node) || !formEl.contains(active)) {
    return false;
  }
  return (
    active instanceof HTMLInputElement ||
    active instanceof HTMLTextAreaElement ||
    active instanceof HTMLSelectElement
  );
}

/** Mount the God-Mode event injection toolbar and bind REST + focus lifecycle handlers. */
export function mountEventInjector(options: EventInjectorOptions): () => void {
  const {
    formEl,
    locationSelectEl,
    textInputEl,
    submitBtnEl,
    feedbackEl,
    onFocusChange,
  } = options;

  if (
    formEl === null ||
    locationSelectEl === null ||
    textInputEl === null ||
    submitBtnEl === null
  ) {
    return () => {};
  }

  let disposed = false;
  let isSubmitting = false;
  let isLoadingLocations = false;
  let locationsLoaded = false;
  let isFocused = false;

  const setFocused = (nextFocused: boolean): void => {
    if (isFocused !== nextFocused) {
      isFocused = nextFocused;
      onFocusChange?.(nextFocused);
    }
  };

  const setFeedback = (
    message: string,
    variant: "neutral" | "ok" | "error",
  ): void => {
    if (feedbackEl === null) {
      return;
    }
    feedbackEl.className =
      variant === "neutral" ? "feedback" : `feedback ${variant}`;
    feedbackEl.textContent = message;
  };

  const loadLocations = async (): Promise<void> => {
    if (disposed || isLoadingLocations || locationsLoaded) {
      return;
    }
    isLoadingLocations = true;
    try {
      const world = await fetchWorld();
      if (disposed) {
        return;
      }

      const previousSelection = locationSelectEl.value;
      const defaultOpt = document.createElement("option");
      defaultOpt.value = "";
      defaultOpt.textContent = "All Village";

      const seen = new Set<string>();
      const locationOpts: HTMLOptionElement[] = [];
      for (const loc of world.locations) {
        if (!loc.name || seen.has(loc.name)) {
          continue;
        }
        seen.add(loc.name);
        const opt = document.createElement("option");
        opt.value = loc.name;
        opt.textContent = loc.name;
        locationOpts.push(opt);
      }

      locationSelectEl.replaceChildren(defaultOpt, ...locationOpts);
      if (previousSelection && seen.has(previousSelection)) {
        locationSelectEl.value = previousSelection;
      }
      locationsLoaded = true;
    } catch {
      // Keep the "All Village" fallback when backend metadata is unavailable.
    } finally {
      isLoadingLocations = false;
    }
  };

  const handleFocusIn = (): void => {
    setFocused(true);
    if (!locationsLoaded) {
      void loadLocations();
    }
  };

  const handleFocusOut = (event: FocusEvent): void => {
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && formEl.contains(nextTarget)) {
      return;
    }
    setFocused(false);
  };

  const handleSubmit = async (event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    if (isSubmitting) {
      return;
    }

    const text = textInputEl.value.trim();
    if (!text) {
      setFeedback("Enter an event description first.", "error");
      return;
    }

    const selectedLocation = locationSelectEl.value.trim();
    isSubmitting = true;
    submitBtnEl.disabled = true;
    setFeedback("Injecting event...", "neutral");

    try {
      const response = await injectEvent({
        text,
        location: selectedLocation || null,
      });
      if (disposed) {
        return;
      }
      textInputEl.value = "";
      const count = response.affected_agents.length;
      setFeedback(`Alerted ${count} villager(s)`, "ok");
    } catch (err: unknown) {
      if (disposed) {
        return;
      }
      const message =
        err instanceof Error ? err.message : "Failed to inject event.";
      setFeedback(message, "error");
    } finally {
      isSubmitting = false;
      submitBtnEl.disabled = false;
      if (!disposed) {
        setFocused(isFormControlFocused(formEl));
      }
    }
  };

  formEl.addEventListener("focusin", handleFocusIn);
  formEl.addEventListener("focusout", handleFocusOut);
  formEl.addEventListener("submit", handleSubmit);

  void loadLocations();

  return () => {
    disposed = true;
    formEl.removeEventListener("focusin", handleFocusIn);
    formEl.removeEventListener("focusout", handleFocusOut);
    formEl.removeEventListener("submit", handleSubmit);
    setFocused(false);
  };
}
