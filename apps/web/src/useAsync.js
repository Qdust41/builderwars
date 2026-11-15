import { useCallback, useEffect, useState } from "react";
export function useAsync(load, deps) {
    const [data, setData] = useState();
    const [error, setError] = useState();
    const [loading, setLoading] = useState(true);
    const [tick, setTick] = useState(0);
    const reload = useCallback(() => setTick((t) => t + 1), []);
    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        load()
            .then((value) => !cancelled && (setData(value), setError(undefined)))
            .catch((err) => !cancelled && setError(String(err)))
            .finally(() => !cancelled && setLoading(false));
        return () => {
            cancelled = true;
        };
    }, [...deps, tick]);
    return { data, error, loading, reload };
}
