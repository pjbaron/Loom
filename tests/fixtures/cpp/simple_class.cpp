// Simple C++ class implementation for testing

#include "simple_class.h"
#include <iostream>

namespace MyNamespace {

SimpleClass::SimpleClass()
    : m_value(0)
    , m_name("default")
{
}

SimpleClass::SimpleClass(int value)
    : m_value(value)
    , m_name("default")
{
}

SimpleClass::~SimpleClass()
{
}

int SimpleClass::getValue() const
{
    return m_value;
}

std::string SimpleClass::getName() const
{
    return m_name;
}

void SimpleClass::setValue(int value)
{
    m_value = value;
    internalHelper();
}

void SimpleClass::setName(const std::string& name)
{
    m_name = name;
}

void SimpleClass::process()
{
    std::cout << "Processing: " << m_name << " = " << m_value << std::endl;
}

SimpleClass* SimpleClass::create(int value)
{
    return new SimpleClass(value);
}

void SimpleClass::internalHelper()
{
    // Internal helper implementation
}

void helperFunction(SimpleClass& obj)
{
    obj.process();
}

template<typename T>
void Container<T>::add(const T& item)
{
    m_items.push_back(item);
}

template<typename T>
T Container<T>::get(int index) const
{
    return m_items[index];
}

} // namespace MyNamespace
