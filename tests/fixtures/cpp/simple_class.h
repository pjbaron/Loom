// Simple C++ class header for testing

#pragma once

#include <string>
#include <vector>

namespace MyNamespace {

/**
 * A simple class for testing purposes.
 */
class SimpleClass {
public:
    SimpleClass();
    explicit SimpleClass(int value);
    virtual ~SimpleClass();

    // Getters
    int getValue() const;
    std::string getName() const;

    // Setters
    void setValue(int value);
    void setName(const std::string& name);

    // Virtual method
    virtual void process();

    // Static method
    static SimpleClass* create(int value);

protected:
    int m_value;
    std::string m_name;

private:
    void internalHelper();
};

// Free function
void helperFunction(SimpleClass& obj);

// Template class
template<typename T>
class Container {
public:
    void add(const T& item);
    T get(int index) const;

private:
    std::vector<T> m_items;
};

} // namespace MyNamespace
